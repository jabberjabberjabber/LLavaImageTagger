import os, json, time, re, argparse, exiftool, requests, base64
from pillow_heif import register_heif_opener
from PIL import Image
import io
import random
import rawpy
import uuid
from tinydb import TinyDB, where
from json_repair import repair_json as rj
from datetime import timedelta
from fix_busted_json import first_json

nlp = None

def normalize_keyword(keyword):
    keyword = str(keyword).lower().strip()
    # Replace underscores with spaces
    keyword = re.sub(r'[_]+', ' ', keyword)
    # Remove any other non-alphanumeric characters
    keyword = re.sub(r'[^\w\s-]', '', keyword)
    # Replace multiple spaces with a single space
    keyword = re.sub(r'\s+', ' ', keyword)
    return keyword
    
def load_spacy():
    global nlp
    if nlp is None:
        import spacy
        nlp = spacy.load("en_core_web_sm")
        print("Loaded spaCy for lemmatization")
    return nlp

def lemmatize_keyword(keyword, nlp_model):
    doc = nlp(keyword)
    # Use the lemma if it's different from the original word, otherwise keep the original
    lemmatized = " ".join([token.lemma_ if token.lemma_ != token.text else token.text for token in doc])
    lemmatized = re.sub(r'\s*-\s*', '-', lemmatized)
    return lemmatized

"""
def process_keywords(keywords):
    processed_keywords = set()
    for keyword in keywords:
        normalized = normalize_keyword(keyword)
        lemmatized = lemmatize_keyword(normalized)
        processed_keywords.add(lemmatized)
    return sorted(processed_keywords)
"""    
    
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

def clean_json(data):
    if data is None:
        return {"Keywords": []}
    if isinstance(data, dict):
        return data  # If it's already a dict, just return it
    if isinstance(data, str):
        # Try to extract JSON from the string
        pattern = r"```json\s*(.*?)\s*```"
        match = re.search(pattern, data, re.DOTALL)
        if match:
            data = match.group(1).strip()
        else:
            # If no JSON block found, try to find anything that looks like JSON
            json_str = re.search(r"\{.*\}", data, re.DOTALL)
            if json_str:
                data = json_str.group(0)

        data = re.sub(r"\n", " ", data)
        data = re.sub(r'["""]', '"', data)

        try:
            return json.loads(rj(data))
        except json.JSONDecodeError:
            try:
                return json.loads(first_json(rj(data)))
            except:
                try:
                    return json.loads(first_json(rj('{' + data + '}')))
                except:
                    try:
                        return json.loads(rj('{' + data + '}'))
                    except:
                        print(f"Failed to parse JSON: {data}")
                        return {"Keywords": []}
    return {"Keywords": []}
    
class Config:
    def __init__(self):
        self.directory = None
        self.api_url = None
        self.api_password = None
        self.no_crawl = False
        self.overwrite = False
        self.dry_run = False
        self.write_keywords = False
        self.update_keywords = False
        self.reprocess = False
        self.keywords_count = 7
        self.max_workers = 4

    @classmethod
    def from_args(cls):
        parser = argparse.ArgumentParser(description="Image Indexer")
        parser.add_argument("directory", help="Directory containing the files")
        parser.add_argument("--api-url", default="http://localhost:5001", help="URL for the LLM API")
        parser.add_argument("--api-password", default="", help="Password for the LLM API")
        parser.add_argument("--no-crawl", action="store_true", help="Disable recursive indexing")
        parser.add_argument("--overwrite", action="store_true", help="Overwrite existing file metadata without making backup")
        parser.add_argument("--dry-run", action="store_true", help="Don't write any files")
        parser.add_argument("--write-keywords", action="store_true", help="Write Keywords metadata")
        parser.add_argument("--reprocess", action="store_true", help="Reprocess files")
        parser.add_argument("--update-keywords", action="store_true", help="Update Keywords metadata")
        parser.add_argument("--keywords-count", type=int, default=7, help="Number of keywords to generate")
        parser.add_argument("--max-workers", type=int, default=4, help="Maximum number of worker threads")
        parser.add_argument("--lemmatize", action="store_true", help="Apply lemmatization to keywords")
        args = parser.parse_args()
        
        config = cls()
        for key, value in vars(args).items():
            setattr(config, key, value)
        return config
        
class ImageProcessor:

    def __init__(self):
       
        register_heif_opener()
     
    def route_image(self, file_path, image_type):
        try:
            if image_type == 'RAW':
                return self.process_raw_image(file_path)   
            elif image_type in ['PNG', 'JPEG', 'BMP']:
                return self.encode_file_to_base64(file_path)
            else:
                return self.process_image(file_path)
                
        except Exception as e:
            self.logger.error(f"Image unsupported {file_path}: {str(e)}")
        return None
        
    def encode_file_to_base64(self, file_path):
        with open(file_path, 'rb') as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')    
            
    def process_image(self, file_path):
        try:
            with Image.open(file_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                buffer = io.BytesIO()
                img.save(buffer, format='PNG')
                png_data = buffer.getvalue()
                
                return base64.b64encode(png_data).decode('utf-8')
        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {str(e)}")
        return None
        
    def process_raw_image(self, file_path):
        with rawpy.imread(file_path) as raw:
            
            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    return base64.b64encode(thumb.data).decode('utf-8')
            
            except:
                pass
            
            rgb = raw.postprocess()
            img = Image.fromarray(rgb)
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode('utf-8')

class LLMProcessor:    
    def __init__(self, config):
        self.config = config
        #self.callback = callback
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
        
        # this prompt works well, you can change it if you want, but comment it out in
        # case you want to use it again.

        self.metadata_instruction = f"Generate a list of IPTC keywords for the image you see. Each keyword will be one or two words and will describe each of the following as applicable and separately:\nobjects, people, animals, gender, race, physical appearance, clothing, style, subject, actions, subject, shot framing, professions, relationships, setting, location, concepts, colors, and anything else relevant.\n\nReturn formatted as a JSON object with key Keywords with a single list of keywords as the value.\n\n"
        
        self.api_url = config.api_url
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_password}",
        }
        self.genkey = self._create_genkey()
        
        # you may have to add an entry name for a finetune with
        # a different name than its base
        self.templates = {
            1: {"name": ["Alpaca"], "user": "\n\n### Instruction:\n\n", "assistant": "\n\n### Response:\n\n", "system": ""},
            2: {"name": ["Vicuna", "Wizard", "ShareGPT"], "user": "### Human: ", "assistant": "\n### Assistant: ", "system": ""},
            3: {"name": ["Llama 2", "Llama2", "Llamav2"], "user": "[INST] ", "assistant": " [/INST]", "system": ""},
            4: {"name": ["Llama 3", "Llama3", "Llama-3"], "endTurn": "<|eot_id|>", "system": "", "user": "<|start_header_id|>user<|end_header_id|>\n\n", "assistant": "<|start_header_id|>assistant<|end_header_id|>\n\n"},
            5: {"name": ["Phi-3"], "user": "<|end|><|user|>\n", "assistant": "<end_of_turn><|end|><|assistant|>\n", "system": ""},
            6: {"name": ["Mistral", "bakllava"], "user": "\n[INST] ", "assistant": " [/INST]\n", "system": ""},
            7: {"name": ["Yi"], "user": "<|user|>", "assistant": "<|assistant|>", "system": ""},
            8: {"name": ["ChatML", "obsidian", "Nous", "Hermes", "cpm", "Qwen"], "user": "<|im_start|>user\n", "assistant": "<|im_end|>\n<|im_start|>assistant\n", "system": ""},
            9: {"name": ["WizardLM"], "user": "input:\n", "assistant": "output\n", "system": ""}
        }
        self.model = self._get_model()
        #self.callback = f"Current running model detected as: {self.model.get('name', 'unknown')}"
        self.max_context = self._get_max_context_length()

    def _call_api(self, api_function, payload=None):
        """ The part where we talk to koboldAPI. Open the browser
            and go to http://localhost:5001/api to see all the options.
        """
        if api_function not in self.api_function_urls:
            raise ValueError(f"Invalid API function: {api_function}")
        url = f"{self.api_url}{self.api_function_urls[api_function]}"

        try:
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

    def describe_content(self, base64_image):
        """ You can play with the sampler settings to achieve 
            different results.
            Max length gets expanded as keyword number increases
            to compensate for longer generation.
        """
        prompt = self.get_prompt(instruction=self.metadata_instruction)
        payload = {
            "prompt": prompt,
            "max_length": 250,
            "images": [base64_image],
            "genkey": self.genkey,
            "model": "clip",
            "top_p": 1,
            "top_k": 0,
            "temp": 0.1,
            "rep_pen": 1,
            "min_p": 0.05,
        }
        return self._call_api("generate", payload)

    def _get_model(self):
        """ Calls koboldAPI and asks for the name of the running model.
            Then tries to match a string in the returned text with
            one of the prompt templates. It then loads the template
            into the model dict.
        """
        model_name = self._call_api("model")
        if not model_name:
            return None

        def normalize(s):
            return re.sub(r"[^a-z0-9]", "", s.lower())

        normalized_model_name = normalize(model_name.lower())

        def check_match(template_name):
            if isinstance(template_name, list):
                return any(normalize(name) in normalized_model_name for name in template_name)
            return normalize(template_name) in normalized_model_name

        matched_template = max(
            (
                (template, len(normalize(template["name"] if isinstance(template["name"], str) else template["name"][0])))
                for template in self.templates.values()
                if check_match(template["name"])
            ),
            key=lambda x: x[1],
            default=(None, 0)
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
        prompt = f"{user_part}{instruction}{content}{end_part}{assistant_part}"
        return prompt

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
        
class FileProcessor:
    def __init__(self, config, image_processor, check_paused_or_stopped, callback):
        self.config = config
        self.image_processor = image_processor
        self.llm_processor = LLMProcessor(config)
        self.check_paused_or_stopped = check_paused_or_stopped
        self.callback = callback
        self.db = TinyDB("filedata.json")
        self.nlp_model = None
        self.start_time = time.time()
        self.running_time = 0
        self.files_in_queue = 0
        self.files_done = -1
        if self.config.lemmatize:
            self.nlp_model = load_spacy()
            self.callback("Loaded spaCy for lemmatization")

        self.exiftool_fields = ["XMP:Description", "Subject", "Keywords", "XMP:Identifier", "FileType"]
        
        # untested formats:
        # arq, crm, cr3, crw, ciff, erf, fff, flif, gpr, hdp, wdp,
        # heif, hif, iiq, insp, jpf, jpm, jpx, jph, mef, mos, mpo,
        # nrw, ori, jng, mng, qtif, qti, qif, sr2, x3f
        
        self.image_extensions = {
            "JPEG": [".jpg", ".jpeg", ".jpe", ".jif", ".jfif", ".jfi", ".jp2", ".j2k", ".jpf", ".jpx", ".jpm", ".mj2"],
            "PNG": [".png"],
            "GIF": [".gif"],
            "TIFF": [".tiff", ".tif"],
            "BMP": [".bmp", ".dib"],
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
        
    def get_file_type(self, file_ext):
        
        if not file_ext.startswith('.'):
            
            file_ext = '.' + file_ext
        file_ext = file_ext.lower()
        
        for file_type, extensions in self.image_extensions.items():
            
            if file_ext in [ext.lower() for ext in extensions]:
                #print(file_type)
                return file_type
        
        return None
        
    def check_uuid(self, metadata):
        try:
            
            if metadata.get('XMP:Identifier'):
                if self.db.search(where('XMP:Identifier') == metadata.get('XMP:Identifier')):
                    print(f"UUID found {metadata.get('XMP:Identifier')}")
                    if self.config.reprocess:
                        return metadata
                    else:
                        return None
                else:
                    return metadata
            else:
                metadata['XMP:Identifier'] = str(uuid.uuid4())
                return metadata
                
        except Exception as e:
            print(f"Error checking UUID")
            return None

    def update_db(self, metadata):
        try:
            self.db.upsert(metadata, where('XMP:Identifier') == metadata.get('XMP:Identifier'))
            print(f"DB Updated with UUID: {metadata.get('XMP:Identifier')}")
            return
        except: 
            print(f"Error updating DB with UUID: {metadata.get('XMP:Identifier')}")
            return False
    def mark_for_retry(self, metadata):
        metadata['status'] = 'retry'
        self.update_db(metadata)        
    
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
            self.callback(f"Added folder {directory} to queue containing {len(files)} image files.")
        return files
        
    def process_directory(self, directory):
        files = self.list_files(directory)
        metadata_list = []
        try:
            with exiftool.ExifToolHelper() as et:
                metadata_list = et.get_tags(files, self.exiftool_fields)
        
        except Exception as e:
            self.callback(f"Directory has no images: {directory}")
            print(f"Error loading Exiftool")
        
        
        #self.callback(f"Number of files to process: {len(metadata_list)}")
        
        for metadata in metadata_list:
         
            if self.files_in_queue > 0:
                self.files_in_queue -= 1
            if self.check_pause_stop():
                return
            #print(f"Processing file: {metadata.get('SourceFile', 'unknown')}")
            if metadata:
                self.process_file(metadata)
            else:
                pass

    def process_file(self, metadata):
        try:
            file_path = metadata['SourceFile']
            
            metadata_added = self.check_uuid(metadata)
            
            if metadata_added is None:
                #print(f"File {file_path} has already been processed or is a duplicate")
                return
                
            else:
                metadata = metadata_added    
                
                image_type = self.get_file_type(os.path.splitext(file_path)[1].lower())
                
                if image_type is not None:
                    
                    self.files_done +=1 
                    if self.files_done > 1:
                        end_time = time.time()
                        processing_time = end_time - self.start_time
                        self.running_time += processing_time 
                        average_time = self.running_time / self.files_done
                        
                        self.callback(f"Processing time: {processing_time:.2f}s. Avergage processing time: {average_time:.2f}s") 
                        self.start_time = time.time()
                
                    image_object_or_path = self.image_processor.route_image(file_path, image_type)
                    
                    if image_object_or_path:
                        if not self.update_metadata(metadata, image_object_or_path):
                            self.mark_for_retry(metadata)
                        
                    if self.check_pause_stop():
                        return    
                else:
                    print(f"Not a supported image type: {file_path}")                    
                
        except Exception as e:
            print(f"Error processing: {file_path}")
                                
    def extract_values(self, data):
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return [item for sublist in data.values() for item in (extract_values(sublist) if isinstance(sublist, (dict, list)) else [sublist])]
        else:
            return []
            
    def process_keywords(self, metadata, llm_metadata):
        """ Normalize and optionally lemmatize all keywords. If update is configured,
            combine the old and new keywords.
        """
        all_keywords = set()
        
        if self.config.update_keywords:
            all_keywords.update(metadata.get("IPTC:Keywords", []))
            all_keywords.update(metadata.get("MWG:Keywords", []))
            all_keywords.update(metadata.get("Keywords", []))
            all_keywords.update(metadata.get("XMP:Subject", []))
        
        extracted_keywords = self.extract_values(llm_metadata.get("Keywords", []))
        if extracted_keywords is None:
            extracted_keywords = self.extract_values(llm_metadata.get("keywords", []))
        
        all_keywords.update(extracted_keywords)
        processed_keywords = set()
        
        for keyword in all_keywords:
            normalized = normalize_keyword(keyword)
            #if self.config.lemmatize:
             #   normalized = lemmatize_keyword(normalized, self.nlp_model)
            processed_keywords.add(normalized)

        return list(processed_keywords)
    
    def get_metadata(self, file_path):
        try:
            with exiftool.ExifToolHelper() as et:
                metadata = et.get_tags([file_path], self.exiftool_fields)[0]
            return metadata
        except Exception as e:
            print(f"Error getting metadata for {file_path}: {str(e)}")
            return None
            
    
    def update_metadata(self, metadata, base64_image):
        write = False
        file_path = metadata["SourceFile"]
            
        try:
            llm_metadata = clean_json(self.llm_processor.describe_content(base64_image))
            if llm_metadata["Keywords"] or llm_metadata["keywords"]:
                xmp_metadata = {}
                xmp_metadata["XMP:Identifier"] = metadata["XMP:Identifier"]
                xmp_metadata["IPTC:Keywords"] = ""
                xmp_metadata["XMP:Subject"] = ""
                xmp_metadata["MWG:Keywords"] = self.process_keywords(metadata, llm_metadata)
                output = f"---\nImage: {os.path.basename(file_path)}\nKeywords: " + ", ".join(xmp_metadata.get("MWG:Keywords","")) + f"\nFiles remaining in queue: {self.files_in_queue}"  
        except:
            print(f"CANNOT parse keywords for {file_path}\n")
            return False
     
        try:    
            if self.config.dry_run:
                self.callback(f"{output}\nNOT written to because an because pretend mode is set.\n")
                return True 
            elif self.config.overwrite:
                with exiftool.ExifToolHelper() as et:
                    et.set_tags(
                        file_path,
                        tags=xmp_metadata,
                        params=["-P", "-overwrite_original"],
                    )
                self.update_db(xmp_metadata)
                self.callback(output)
                return True
            else:
                with exiftool.ExifToolHelper() as et:
                    et.set_tags(file_path, tags=xmp_metadata)
                self.update_db(xmp_metadata) 
                self.callback(output)
                return True  
           
        except Exception as e:
            print(f"Error updating metadata for {file_path}:  {str(e)}")
            return False

    def process_retry_files(self):
        retry_files = self.db.search(where('status') == 'retry')
        self.callback(f"Retrying {len(retry_files)} files...")
        
        for metadata in retry_files:
            if self.check_pause_stop():
                return
            self.process_file(metadata)
            
        failed_files = self.db.search(where('status') == 'retry')
        if failed_files:
            self.callback(f"Files that still failed after retry: {len(failed_files)}")
            for metadata in failed_files:
                metadata['status'] = 'failed'
                self.update_db(metadata)
                self.callback(f"Failed file: {metadata['SourceFile']}")
        else:
            self.callback("All retry files processed successfully.")
            
def main(config=None, callback=None, check_paused_or_stopped=None):
    if config is None:
        config = Config.from_args()

    image_processor = ImageProcessor()

    file_processor = FileProcessor(config, image_processor, check_paused_or_stopped, callback)

    if config.no_crawl:
        try:
            file_processor.process_directory(config.directory)
        except Exception as e:
            print(f"An error occurred during processing: {str(e)}")
            if callback:
                callback(f"Error: {str(e)}")
    else:
        directories = [root for root, _, _ in os.walk(config.directory)]

        for directory in directories:
            if check_paused_or_stopped and check_paused_or_stopped():
                print("Processing stopped by user.")
                break
            try:
                file_processor.process_directory(directory)
            except Exception as e:
                print(f"Error processing directory {directory}: {str(e)}")

    # Final pass to retry failed files
    file_processor.process_retry_files()

    failed_files = file_processor.db.search(where('status') == 'failed')
    if failed_files:
        callback(f"Files that failed after retry: {len(failed_files)}")
        for metadata in failed_files:
            callback(f"Failed file: {metadata['SourceFile']}")
    else:
        callback("All files processed successfully.")

if __name__ == "__main__":
    main()