import os, json, time, re, argparse, exiftool, requests, base64, threading, queue, calendar, io, random, rawpy, uuid
from pillow_heif import register_heif_opener
from PIL import Image
from tinydb import TinyDB, where, Query
from json_repair import repair_json as rj
from datetime import timedelta
from fix_busted_json import first_json
from keyword_processor import KeywordProcessor

# TODO:
# =====
# Check file sizes before processing
# Move top functions to a utilities file
# Handle API rejections gracefully
# Check for broken list item

def run_keyword_processing(config, callback):
    if config.keyword_processing in ["expand", "dedupe"]:
        callback(f"Running keyword processing in {config.keyword_processing} mode (be patient)...")
        processor = KeywordProcessor()
        updated_file_keywords = processor.process_directory(config.directory, config.keyword_processing, config.no_crawl)
        
        if updated_file_keywords:
            callback(f"Updating metadata for {len(updated_file_keywords)} files...")
            if config.dry_run is False:
                before_keyword_len, after_keyword_len = processor.update_metadata(updated_file_keywords, config.no_backup)
                callback(f"Keyword processing complete.\nTotal keywords before: {before_keyword_len}, total keywords after: {after_keyword_len}")
            else:
                callback("Not updated: dry-run is enabled")
        else:
            callback("No changes were necessary after keyword processing.")
    else:
        callback("Keyword processing skipped (set to 'keep').")

def normalize_keyword(keyword, banned_words, replaced_words):
    """ Prevents bad keywords by banning regularly malformed 
        sequences or words indicative of bad generations
    """
    keyword = str(keyword).lower().strip()
    
    # Replace underscores with spaces
    keyword = re.sub(r"[_]+", " ", keyword)
    
    # Remove any other non-alphanumeric characters
    keyword = re.sub(r"[^\w\s-]", "", keyword)
    
    # Replace multiple spaces with a single space
    keyword = re.sub(r"\s+", " ", keyword)
    
    if keyword.startswith(""):
        return keyword
    
    words = keyword.split()
    
    # Cannot start with more than two digits
    if re.match(r"^\d{3,}", words[0]):
        return None
    
    # Two word max unless middle word is 'and'
    if len(words) > 2 and words[1] not in ['and', 'or']:
        keyword = ' '.join(words[:2])
    else:
        keyword = ' '.join(words[:3])
    
    if re.match(r"^\d{5,}", keyword) or words[0] in banned_words:
        return None
    
    # New conditions
    words = keyword.split()
    filtered_words = []
    months = [month.lower() for month in calendar.month_name if month]
    days = [day.lower() for day in calendar.day_name]
    
    for word in words:
        # Cannot be less than 2 chars
        if len(word) < 2:
            continue
        # Cannot be a month or a day
        if word in months or word in days:
            continue
        # Cannot be longer than 20 chars per word
        if len(word) > 20:
            continue
        # Cannot have more than one hyphen
        if word.count('-') > 1:
            continue
        filtered_words.append(word)
    
    if not filtered_words:
        return None
    
    return ' '.join(filtered_words)
    
def clean_string(data):
    if isinstance(data, dict):
        data = json.dumps(data)
    if isinstance(data, str):
        data = re.sub(r"\n", "", data)
        data = re.sub(r'["""]', '"', data)
        data = re.sub(r"\\{2}", "", data)
        last_period = data.rfind('.')
        if last_period != -1:
            data = data[:last_period+1]
    return data
    
def markdown_list_to_dict(text):
    """ Searches a string for a markdown formatted
        list, and if one is found, converts it to
        a dict.
    """
    list_pattern = r"(?:^\s*[-*+]|\d+\.)\s*(.+)$"
    list_items = re.findall(list_pattern, text, re.MULTILINE)

    if list_items:
        return {"Keywords": list_items}
    else:
        return None
        
def find_keywords(data):
    if isinstance(data, list):
        data = ' '.join(data)
    if not isinstance(data, str):
        return data
        
    # Define the regex pattern to find 'keyword:' or 'keywords:' case-insensitively
    pattern = re.compile(r'(?i)(keyword|keywords):', re.IGNORECASE)

    # Find the match
    match = pattern.search(data)
    if not match:
        return {}

    # Extract the portion of the string after the matched keyword
    remaining_string = data[match.end():].strip()

    # Initialize the list to hold the keywords
    keywords = []

    # Check for different formats of the list
    if '[' in remaining_string and ']' in remaining_string:
        # JSON-like list format
        try:
            # Extract the list part and evaluate it
            list_part = remaining_string[remaining_string.index('['):remaining_string.index(']')+1]
            keywords = eval(list_part)
        except:
            pass
    elif remaining_string.startswith('-'):
        # Bullet-point list format
        lines = remaining_string.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('-'):
                keywords.append(line[1:].strip())
    else:
        # Comma-separated list format
        keywords = [word.strip() for word in remaining_string.split(',') if word.strip()]

    return {"Keywords": keywords}
    
def clean_json(data):
    """ LLMs like to return all sorts of garbage.
        Even when asked to give a structured output
        the will wrap text around it explaining why
        they chose certain things. This function 
        will pull basically anything useful and turn it
        into a dict
    """
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        copied_data = data[:]
        # Try to extract JSON markdown code
        pattern = r"```json\s*(.*?)\s*```"
        match = re.search(pattern, data, re.DOTALL)
        if match:
            data = match.group(1).strip()
        else:
            
            # If no JSON block found, try to find anything that looks like JSON
            json_str = re.search(r"\{.*\}", data, re.DOTALL)
            if json_str:
                data = json_str.group(0)
                
        # Remove extra newlines and funky quotes 
        data = re.sub(r"\n", " ", data)
        data = re.sub(r'["""]', '"', data)
        try:
            return json.loads(rj(data))
                
            # first_json will return the first json found in a string
            # rj tries to repair json using some heuristics
            return json.loads(first_json(rj(data)))
            
            # Is it a markdown list?
            if result := markdown_list_to_dict(data):
                return result
            
            # The nuclear option - wrap whatever it is around brackets and load it
            # Hopefully normalize_keywords will take care of any garbage
            result = json.loads(first_json(rj("{" + data + "}")))
            if result.get("Keywords"):
                return result
            
            return find_keywords(copied_data)
            
        except:
            print(f"Failed to parse JSON: {data}")
            
    return None


class Config:
    def __init__(self):
        self.directory = None
        self.api_url = None
        self.api_password = None
        self.no_crawl = False
        self.no_backup = False
        self.dry_run = False
        self.overwrite_keywords = False
        self.update_keywords = False
        self.reprocess_failed = False
        self.reprocess_all = False
        self.skip_orphans = True
        self.text_completion = False
        self.gen_count = 150
        self.write_caption = False
        self.skip_processing = False
        self.keyword_processing = "keep"
        self.caption_instruction = "Describe the image in detail. Be specific."
        self.system_instruction = "You are a helpful assistant."
        self.instruction = "Generate at least 14 unique one or two word IPTC Keywords for the image. Cover the following categories as applicable:\\n1. Main subject of the image\\n2. Physical appearance and clothing, gender, age, professions and relationships\\n3. Actions or state of the main elements\\n4. Setting or location, environment, or background\\n5. Notable items, structures, or elements\\n6. Colors and textures, patterns, or lighting\\n7. Atmosphere and mood, time of day, season, or weather\\n8. Composition and perspective, framing, or style of the photo.\\n9. Any other relevant keywords.\\nProvide one or two words. Do not combine words. Generate ONLY a JSON object with the key Keywords with a single list of keywords as follows {\"Keywords\": []}"

    @classmethod
    def from_args(cls):
        parser = argparse.ArgumentParser(description="Image Indexer")
        parser.add_argument("directory", help="Directory containing the files")
        parser.add_argument(
            "--api-url", default="http://localhost:5001", help="URL for the LLM API"
        )
        parser.add_argument(
            "--api-password", default="", help="Password for the LLM API"
        )
        parser.add_argument(
            "--no-crawl", action="store_true", help="Disable recursive indexing"
        )
        parser.add_argument(
            "--no-backup",
            action="store_true",
            help="Don't make a backup of files before writing",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Don't write any files"
        )
        parser.add_argument(
            "--overwrite-keywords", action="store_true", help="Overwrite existing keyword metadata"
        )
        parser.add_argument(
            "--reprocess-all", action="store_true", help="Reprocess all files"
        )
        parser.add_argument(
            "--reprocess-failed", action="store_true", help="Reprocess failed files"
        )
        parser.add_argument(
            "--skip-orphans", action="store_true", help="If a file has a UUID and keywords but is not in the database, skip processing it"
        )
        parser.add_argument(
            "--update-keywords", action="store_true", help="Update existing keyword metadata"
        )
        parser.add_argument(
            "--skip-processing", action="store_true", help="Skip processing and go to post-processing step"
        )
        parser.add_argument(
            "--keyword-processing",
            choices=["keep", "expand", "dedupe"],
            default="keep",
            help="Keyword post-processing method: keep as generated, expand synonyms, or deduplicate"
        )
        parser.add_argument(
            "--gen-count", default=150, help="Number of tokens to generate"
        )
        parser.add_argument("--write-description", action="store_true", help="Write description in separate file")
        args = parser.parse_args()

        config = cls()
        for key, value in vars(args).items():
            setattr(config, key, value)
        return config


class ImageProcessor:
    def __init__(self):
        # For HEIC support 
        register_heif_opener()

    def route_image(self, file_path, image_type):
        """ Checks RAW for embedded JPEG and uses that, 
            if not converts it to JPG. JPG, PNG
            get sent as-is, all others get turned into
            JPGs. Everything is encoded in base64
            to get sent to the LLM
        """
        try:
            if image_type == "RAW":
                return self.process_raw_image(file_path)
            elif image_type in ["JPEG", "BMP", "PNG"]:
                return self.encode_file_to_base64(file_path)
            else:
                return self.process_image(file_path)

        except Exception as e:
            self.logger.error(f"Image unsupported {file_path}: {str(e)}")
        return None

    def encode_file_to_base64(self, file_path):
        with open(file_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def process_image(self, file_path):
        try:
            with Image.open(file_path) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")

                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=95)
                data = buffer.getvalue()

                return base64.b64encode(data).decode("utf-8")
        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {str(e)}")
        return None

    def process_raw_image(self, file_path):
        with rawpy.imread(file_path) as raw:

            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    return base64.b64encode(thumb.data).decode("utf-8")

            except:
                pass

            rgb = raw.postprocess()
            img = Image.fromarray(rgb)
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=95)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")


class LLMProcessor:
    def __init__(self, config):
        self.config = config
        self.api_function_urls = {
            "tokencount": "/api/extra/tokencount",
            "interrogate": "/api/v1/generate",
            "max_context_length": "/api/extra/true_max_context_length",
            "check": "/api/generate/check",
            "abort": "/api/extra/abort",
            "version": "/api/extra/version",
            "model": "/api/v1/model",
            "generate": "/api/v1/generate",
        }

        self.instruction = config.instruction

        self.api_url = config.api_url
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_password}",
        }
        self.genkey = self._create_genkey()
        self.caption_instruction = config.caption_instruction
        # you may have to add an entry name for a finetune with
        # a different name than its base
        self.templates = {
            1: {
                "name": ["Alpaca"],
                "user": "\n\n### Instruction:\n\n",
                "assistant": "\n\n### Response:\n\n",
                "system": None,
            },
            2: {
                "name": ["Vicuna", "Wizard", "ShareGPT"],
                "user": "### Human: ",
                "assistant": "\n### Assistant: ",
                "system": None,
            },
            3: {
                "name": ["Llama 2", "Llama2", "Llamav2"],
                "user": " [/INST][INST] ",
                "assistant": " [/INST]",
                "system": None,
            },
            4: {
                "name": ["Llama 3", "Llama3", "Llama-3"],
                "endTurn": "<|eot_id|>\n",
                "system": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n",
                "system": None,
                "user": "<|start_header_id|>user<|end_header_id|>\n\n",
                "assistant": "<|start_header_id|>assistant<|end_header_id|>\n\n",
            },
            5: {
                "name": ["Phi-3"],
                "user": "<|end|><|user|>\n",
                "assistant": "<end_of_turn><|end|><|assistant|>\n",
                "system": None,
            },
            6: {
                "name": ["Mistral", "bakllava"],
                "user": "\n[INST] ",
                "assistant": " [/INST]\n",
                "system": None,
            },
            7: {
                "name": ["Yi"],
                "user": "<|user|>",
                "assistant": "<|assistant|>",
                "system": None,
            },
            8: {
                "name": ["ChatML", "obsidian", "Nous", "Hermes", "cpm", "Qwen", "Josie"],
                "user": "<|im_end|>\n<|im_start|>user\n",
                "assistant": "<|im_end|>\n<|im_start|>assistant\n",
                "system": "<|im_start|>system\n",
            },
            9: {
                "name": ["WizardLM"],
                "user": "input:\n",
                "assistant": "output\n",
                "system": None,
            },
        }
        self.model = self._get_model()
        self.max_context = self._get_max_context_length()

    def _call_api(self, api_function, payload=None):
        """ The part where we talk to koboldAPI. Open the browser
            and go to http://localhost:5001/api to see all the options.
        """
        if api_function not in self.api_function_urls:
            raise ValueError(f"Invalid API function: {api_function}")
        url = f"{self.api_url}{self.api_function_urls[api_function]}"

        try:
            # Some API calls are POSTs and some are GETs, and the responses
            if api_function in ["tokencount", "generate", "check", "interrogate"]:
                response = requests.post(url, json=payload, headers=self.headers)
                result = response.json()
                if api_function == "tokencount":
                    return int(result.get("value"))
                else:
                    return result["results"][0].get("text")
            else:
                response = requests.get(url, json=payload, headers=self.headers)
                result = response.json()
                return result.get("result", None)
        except requests.RequestException as e:
            print(f"Error calling API: {str(e)}")
            return None

    def describe_content(self, base64_image, task="keywords"):
        """ Samplers should not be used but Kobold sets some by default 
            if they aren't specified
        """
        if task == "keywords":
            instruction = self.instruction
        elif task == "caption":
            instruction = self.caption_instruction
        else:
            print(f"Invalid task {task}")
            return None
        prompt = self.get_prompt(instruction)
        payload = {
            "prompt": prompt,
            "max_length": self.config.gen_count,
            "images": [base64_image],
            "genkey": self.genkey,
            #"model": "clip",
            "top_p": 1,
            "top_k": 0,
            "temp": 0,
            "rep_pen": 1,
            "min_p": 0,
        }
        return self._call_api("generate", payload)

    def _get_model(self):
        """ Calls koboldAPI and asks for the name of the running model.
            Then tries to match a string in the returned text with
            one of the prompt templates. It then loads the template
            into the model dict.
        """
        if self.config.text_completion:
            return { "name": ["Completion"],
                "user": "",
                "assistant": "",
                "system": None,
            }
        model_name = self._call_api("model")
        if not model_name:
            return None

        def normalize(s):
            return re.sub(r"[^a-z0-9]", "", s.lower())

        normalized_model_name = normalize(model_name.lower())

        def check_match(template_name):
            if isinstance(template_name, list):
                return any(
                    normalize(name) in normalized_model_name for name in template_name
                )
            return normalize(template_name) in normalized_model_name

        matched_template = max(
            (
                (
                    template,
                    len(
                        normalize(
                            template["name"]
                            if isinstance(template["name"], str)
                            else template["name"][0]
                        )
                    ),
                )
                for template in self.templates.values()
                if check_match(template["name"])
            ),
            key=lambda x: x[1],
            default=(None, 0),
        )[0]

        return matched_template if matched_template else self.templates[1]

    def get_prompt(self, instruction="", content=""):
        """ Uses the instruct templates to create a prompt with the proper
            start and end sequences. If the model name does not contain
            the name of the model it was based on, these may be incorrect.
        """
                
        user_part = self.model["user"]
        assistant_part = self.model["assistant"]
        end_part = self.model.get("endTurn", "")
        if system_part := self.model.get("system"):
            return f"{system_part}{self.config.system_instruction}{end_part}{user_part}{instruction}{content}{end_part}{assistant_part}"
        else:
            return f"{user_part}{instruction}{content}{end_part}{assistant_part}"
        
    @staticmethod
    def _create_genkey():
        """ Prevents kobold from returning your generation to another
            query.
        """
        return f"KCPP{''.join(str(random.randint(0, 9)) for _ in range(4))}"

    def _get_max_context_length(self):
        return self._call_api("max_context_length")

    def _get_token_count(self, content):
        payload = {"prompt": content, "genkey": self.genkey}
        return self._call_api("tokencount", payload)

class BackgroundIndexer(threading.Thread):
    def __init__(self, root_dir, metadata_queue, file_extensions, no_crawl=False):
        threading.Thread.__init__(self)
        self.root_dir = root_dir
        self.metadata_queue = metadata_queue
        self.file_extensions = file_extensions
        self.no_crawl = no_crawl
        self.total_files_found = 0
        self.indexing_complete = False
        

    def run(self):
        if self.no_crawl:
            self._index_directory(self.root_dir)
        else:
            for root, _, _ in os.walk(self.root_dir):
                self._index_directory(root)
        self.indexing_complete = True

    def _index_directory(self, directory):
        files = []
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path) and any(file_path.lower().endswith(ext) for ext in self.file_extensions):
                files.append(file_path)
        
        if files:
            self.total_files_found += len(files)
            self.metadata_queue.put((directory, files))
            
class FileProcessor:
    def __init__(self, config, image_processor, check_paused_or_stopped, callback):
        self.config = config
        self.image_processor = image_processor
        self.llm_processor = LLMProcessor(config)
        self.check_paused_or_stopped = check_paused_or_stopped
        self.callback = callback
        if os.path.isdir(config.directory):
            self.db = TinyDB(f"{os.path.join(config.directory, 'llmii.json')}")
        else:
            self.db = TinyDB("llmii.json")
        self.files_in_queue = 0
        self.total_processing_time = 0
        self.files_processed = 0
        self.files_completed = 0
        
        # Words in the prompt tend to get repeated back by certain models
        self.banned_words = ["main", "no", "year", "years", "unspecified", "perspective", "unknown", "standard", "unindentified", "type", "time", "category", "living", "actions", "setting", "objects", "visual", "atmosphere", "composition", "mood", "textures", "weather", "season", "structures", "elements", "location", "environment", "background", "activities", "elements", "appearance", "gender", "professions", "relationships", "identify"]
        
        self.replaced_words = {}
          
        # These are the fields we check. ExifTool returns are kind of strange, not always
        # conforming to where they are or what they actually are named
        self.exiftool_fields = [
            #"XMP:Description",
            "MWG:Keywords",
            "XMP:Identifier",
            
            #"FileType",
        ]

        # untested formats:
        # arq, crm, cr3, crw, ciff, erf, fff, flif, gpr, hdp, wdp,
        # heif, hif, iiq, insp, jpf, jpm, jpx, jph, mef, mos, mpo,
        # nrw, ori, jng, mng, qtif, qti, qif, sr2, x3f
        
        self.image_extensions = {
            "JPEG": [
                ".jpg",
                ".jpeg",
                ".jpe",
                ".jif",
                ".jfif",
                ".jfi",
                ".jp2",
                ".j2k",
                ".jpf",
                ".jpx",
                ".jpm",
                ".mj2",
            ],
            "PNG": [".png"],
            "GIF": [".gif"],
            "TIFF": [".tiff", ".tif"],
            #"BMP": [".bmp", ".dib"],
            "WEBP": [".webp"],
            "HEIF": [".heif", ".heic"],
            "RAW": [
                ".raw",  # Generic RAW
                ".arw",  # Sony
                ".cr2",  # Canon
                ".cr3",  # Canon (newer format)
                ".dng",  # Adobe Digital Negative
                ".nef",  # Nikon
                ".nrw",  # Nikon
                ".orf",  # Olympus
                ".pef",  # Pentax
                ".raf",  # Fujifilm
                ".rw2",  # Panasonic
                ".srw",  # Samsung
                ".x3f",  # Sigma
                ".erf",  # Epson
                ".kdc",  # Kodak
                ".rwl",  # Leica
            ],
        }
        self.metadata_queue = queue.Queue()
        self.indexer = BackgroundIndexer(
            config.directory, 
            self.metadata_queue, 
            [ext for exts in self.image_extensions.values() for ext in exts], 
            config.no_crawl
        )
        self.indexer.start()
        
    def get_file_type(self, file_ext):
        """ If the filetype is supported, return the key
            so .nef would return RAW. Otherwise return
            None so we know it is not supported.
        """
        if not file_ext.startswith("."):
            file_ext = "." + file_ext
        file_ext = file_ext.lower()
        for file_type, extensions in self.image_extensions.items():
            if file_ext in [ext.lower() for ext in extensions]:
                return file_type
        return None

    def check_uuid(self, metadata, file_path):
        """ Conditionals; very important or we end up with multiple
            DB entries or end up reprocessing files for no reason
        """ 
        
        try:
            identifier = metadata.get("XMP:Identifier")
            source_file = self.db.get(where("SourceFile") == file_path)
            existing_entry = self.db.get(where("XMP:Identifier") == identifier)
            are_keywords = False
            if metadata.get("Keywords"):
                are_keywords = True
            
            # Case 1: File has a UUID in metadata
            if identifier:
                if self.config.reprocess_all:
                    return metadata
                if existing_entry:    
                    if existing_entry.get("status") == "failed":
                        if self.config.reprocess_failed:
                            return metadata
                    if existing_entry.get("status") == "retry":
                        return metadata
                    return None 
                # Orphan -- has UUID and Keywords but not in db
                if self.config.skip_orphans and are_keywords:
                    return None
                return metadata  

            # Case 2: File has no UUID in metadata
            else:
                # Check if there's a database entry for this file path
                if source_file:
                    
                    # File has a database entry but no UUID in metadata
                    if source_file.get("status") == "failed":
                        if self.config.reprocess_failed:

                            # Remove the file path and status from the database entry
                            self.db.remove(Query().SourceFile == file_path)
                            metadata["XMP:Identifier"] = str(uuid.uuid4())
                            return metadata  # Process the file as if it were new
                        else:
                            return None  # Skip failed file if not retrying
                    elif source_file.get("status") == "retry":
                        return metadata
                
                # No database entry or UUID, treat as new file
                else:
                    metadata["XMP:Identifier"] = str(uuid.uuid4())
                    return metadata  # New file

        except Exception as e:
            print(f"Error checking UUID: {str(e)}")
            return None
            
    def update_db(self, metadata):
        if self.config == "dry_run":
            return
        try:
            uuid = metadata.get("XMP:Identifier")
            
            db_entry = {
                "XMP:Identifier": uuid,
                "status": metadata.get("status", "success")
            }
            # Successful processing should not have a sourcefile entry
            if metadata.get("status") in ["failed", "retry"]:
                db_entry["SourceFile"] = metadata.get("SourceFile")
            self.db.upsert(db_entry, where("XMP:Identifier") == uuid)
            print(f"DB Updated with UUID: {uuid}")
        except Exception as e:
            print(f"Error updating DB with UUID: {uuid}: {str(e)}")
                        
    def check_pause_stop(self):
        if self.check_paused_or_stopped():
            while self.check_paused_or_stopped():
                time.sleep(0.1)
            if self.check_paused_or_stopped():
                return True
        return False

    def list_files(self, directory):
        files = []
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                if self.get_file_type(os.path.splitext(filename)[1].lower()):
                    files.append(file_path)
        if files:
            self.files_in_queue += len(files)
            self.callback(
                f"Added folder {directory} to queue containing {len(files)} image files."
            )
        return files

    def process_directory(self, directory):
        while not (self.indexer.indexing_complete and self.metadata_queue.empty()):
            if self.check_pause_stop():
                return
            try:
                directory, files = self.metadata_queue.get(timeout=1)
                self.callback(f"Processing directory: {directory}")
                metadata_list = self._get_metadata_batch(files)
                
                for metadata in metadata_list:
                    self.files_processed += 1
                    
                    if metadata:
                        keywords = metadata.get("Keywords", [])
                        if metadata.get("Composite:Keywords"):
                            keywords += metadata.get("Composite:Keywords")
                        if metadata.get("Subject"):
                            keywords += metadata.get("Subject")
                        if metadata.get("IPTC:Keywords"):
                            keywords += metadata.get("IPTC:Keywords")                            
                        if keywords:
                            metadata["Keywords"] = keywords
                        self.process_file(metadata)
                    
                    if self.check_pause_stop():
                        return
                self.files_processed +=1
                self.update_progress()
                
            except queue.Empty:
                continue
                
    def _get_metadata_batch(self, files):
        #try:
        with exiftool.ExifToolHelper(check_execute=False) as et:
            
            return et.get_tags(files, tags=self.exiftool_fields)         
            #print(tags)
            
        #except Exception as e:
        #    print("Error")
        #    return []

    def update_progress(self):
        files_processed = self.files_processed
        files_remaining = self.indexer.total_files_found - files_processed
        self.callback(f"Directory processed. Files remaining in queue: {files_remaining}")
        
    def process_file(self, metadata):
        """ This is a lot more complicated than it should be.
            We only use UUID set in XMP:Identifier to ID files
            so that the files being moved around or renamed 
            will not affect their status. Thus we need to 
            at least temporarily maintain a state for them
            as they are being processed and if the process stops.
        """
        try:    
            # ExifTool always returns 'SourceFile' as the file full path
            # whether it is asked for or not
            file_path = metadata["SourceFile"]
            
            # If the file doesn't exist anymore, remove it from the database
            if not os.path.isfile(file_path):
                if metadata.get("XMP:Identifier"):
                    self.db.remove(where("XMP:Identifier") == metadata.get("XMP:Identifier"))
                    self.callback(f"Removed missing file from database: {file_path}")
                return

            if not self.config.dry_run:
                metadata_added = self.check_uuid(metadata, file_path)
                if metadata_added is None:
                    #self.files_processed += 1 
                    return
                else:
                    metadata = metadata_added

            image_type = self.get_file_type(os.path.splitext(file_path)[1].lower())

            if image_type is not None:
                start_time = time.time()
                # Send image encoded in base64 to be processed by LLM
                image_object_or_path = self.image_processor.route_image(file_path, image_type)
                if image_object_or_path:
                    if self.config.write_caption:
                        caption = self.write_caption(image_object_or_path)
                        if caption:
                            metadata["Description"] = caption
                            #print (metadata["Description"])
                    metadata = self.update_metadata(metadata, image_object_or_path)
                    
                    if metadata.get("status") == "success":    
                        end_time = time.time()
                        processing_time = end_time - start_time
                        self.total_processing_time += processing_time
                        self.files_completed += 1
                        
                        in_queue = self.indexer.total_files_found - self.files_processed
                        average_time = self.total_processing_time / self.files_completed
                        time_left = average_time * in_queue
                        time_left_unit = "s"
                        if time_left > 180:
                            time_left = time_left / 60
                            time_left_unit = "mins"
                        
                        self.callback(
                            f"Processing time: {processing_time:.2f}s. Average processing time: {average_time:.2f}s"
                        )
                        self.callback(
                            f"Processed: {self.files_processed}, In queue: {in_queue}, Time remaining (est): {time_left:.2f}{time_left_unit}"
                        )
                        return
                        
                    elif metadata.get("status") == "failed":
                        if not self.config.dry_run:
                            self.update_db(metadata)
                        return
                    elif metadata.get("status") == "retry":
                        self.process_file(metadata)
                    else:
                        print(f"Error processing file: {file_path}")
                        return
                if self.check_pause_stop():
                    return
            else:
                print(f"Not a supported image type: {file_path}")

        except Exception as e:
            print(f"Error processing: {file_path}: {str(e)}")
            metadata["status"] = "failed"
            if not self.config.dry_run:
                self.update_db(metadata)
            return
                
    def extract_values(self, data):
        """ Goes through a dict and pulls all the 
            values out and returns them as a list
            Part of the output processing from whatever
            the LLM gives us.
        """
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return [
                item
                for sublist in data.values()
                for item in (
                    extract_values(sublist)
                    if isinstance(sublist, (dict, list))
                    else [sublist]
                )
            ]
        else:
            return []

    def process_keywords(self, metadata, llm_metadata):
        """ Normalize extracted keywords and deduplicate them.
            If update is configured, combine the old and new keywords.
            Only extracted keywords are normalized, the rest are added to the set as-is.
        """
        all_keywords = set()
        if self.config.update_keywords:
            all_keywords.update(metadata.get("Keywords", []))

        extracted_keywords = self.extract_values(llm_metadata.get("Keywords", []))
        if extracted_keywords is None:
            extracted_keywords = self.extract_values(llm_metadata.get("keywords", []))

        processed_keywords = set()

        # Normalize only the extracted keywords
        for keyword in extracted_keywords:
            normalized = normalize_keyword(keyword, self.banned_words, self.replaced_words)
            if normalized:
                processed_keywords.add(normalized)

        # Add the rest of the keywords without normalization
        processed_keywords.update(all_keywords)

        if processed_keywords:        
            return list(processed_keywords)
        else:
            return None
    
    def write_caption(self, base64_image):
        task = "caption"
        caption = ""
        try:
            return clean_string(self.llm_processor.describe_content(base64_image, task))
        except:
            return 
        
    def update_metadata(self, metadata, base64_image):
        """ The meat and potatoes. It should be pretty easy to follow.
            First query the LLM, fix the inevitably malformed JSON,
            check to see if there is a dict with value Keywords. Put them
            in, clearing other keyword fields. If it fails any part, mark retry
            and try again. Another fail gets marked as fail. exiftool helper
            is called at the end to put the metdata in.
        """
        
        file_path = metadata["SourceFile"]
        
        try:
            llm_metadata = clean_json(self.llm_processor.describe_content(base64_image))

            if llm_metadata["Keywords"] or llm_metadata["keywords"]:
                xmp_metadata = {}
                xmp_metadata["XMP:Description"] = metadata.get("Description")
                xmp_metadata["XMP:Identifier"] = metadata.get(
                    "XMP:Identifier", str(uuid.uuid4())
                )
                xmp_metadata["IPTC:Keywords"] = ""
                xmp_metadata["XMP:Subject"] = ""
                xmp_metadata["MWG:Keywords"] = self.process_keywords(
                    metadata, llm_metadata
                )
                output = (
                    f"---\nImage: {os.path.basename(file_path)}\nKeywords: "
                    + ", ".join(xmp_metadata.get("MWG:Keywords", ""))
                )
                if xmp_metadata.get("XMP:Description"):
                    output +=  (f"\nCaption: {xmp_metadata.get('XMP:Description')}")
        except:
            print(f"CANNOT parse keywords for {file_path}")
            if metadata.get("status") == "retry" or metadata.get("status") == "failed":
                metadata["status"] = "failed"
                self.callback(f"\n---\nCANNOT parse keywords for {file_path}; it has been retried and is marked failed.")
            else:
                metadata["status"] = "retry"
             
            return metadata

        if self.config.dry_run:
            self.callback(f"{output}\nNOT written because dry run mode is set.\n")
            metadata["status"] = "success"
            return metadata
        else:
            try:
                if self.config.no_backup:
                    with exiftool.ExifToolHelper() as et:
                        et.set_tags(
                            file_path,
                            tags=xmp_metadata,
                            params=["-P", "-overwrite_original"],
                        )
                else:
                    with exiftool.ExifToolHelper() as et:
                        et.set_tags(file_path, tags=xmp_metadata)
                metadata["status"] = "success"
                xmp_metadata["status"] = "success"
                self.update_db(xmp_metadata)
                self.callback(output)
                return metadata
            
            except Exception as e:
                print(f"Error updating metadata for {file_path}: {str(e)}")
                if metadata.get("status") == "retry" or metadata.get("status") == "failed":
                    metadata["status"] = "failed"
                    self.callback(f"\n---\nCANNOT parse keywords for {file_path}; it has been retried and is marked failed.")
                else:
                    metadata["status"] = "retry"
                    
                return metadata

def main(config=None, callback=None, check_paused_or_stopped=None):
    if config is None:
        config = Config.from_args()

    if config.skip_processing is False:        
        image_processor = ImageProcessor()

        file_processor = FileProcessor(
            config, image_processor, check_paused_or_stopped, callback
        )

        try:
            file_processor.process_directory(config.directory)
            run_keyword_processing(config, callback)
        except Exception as e:
            print(f"An error occurred during processing: {str(e)}")
            if callback:
                callback(f"Error: {str(e)}")
        finally:
            print("Waiting for indexer to complete...")
            file_processor.indexer.join()
            print("Indexing completed.")
    else:
    
        try:
            run_keyword_processing(config, callback)
            print("Postprocessing completed.")
            if callback:
                callback("Postprocessing completed.")
        except Exception as e:
            print(f"An error occurred during processing: {str(e)}")
            if callback:
                callback(f"Error: {str(e)}")

if __name__ == "__main__":
    main()
