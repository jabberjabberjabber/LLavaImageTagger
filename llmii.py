import os, json, time, re, argparse, exiftool, threading, queue, calendar, io, uuid
import copy
import shutil
import sys

from json_repair import repair_json as rj
from datetime import timedelta
from llmii_utils import first_json, de_pluralize, AND_EXCEPTIONS
from koboldapi import KoboldAPICore, ImageProcessor
    
def split_on_internal_capital(word):
    """ Split a word if it contains a capital letter after the 4th position.
        Returns the original word if no split is needed, or the split 
        version if a capital is found.
        
        Examples:
            BlueSky -> Blue Sky
            microService -> micro Service
    """
    if len(word) <= 4:
        return word
    for i in range(4, len(word)):
        if word[i].isupper():
            return word[:i] + " " + word[i:]
            
    return word

def normalize_keyword(keyword, banned_words):
    """ Normalizes keywords according to specific rules:
        - Splits unhyphenated compound words on internal capitals
        - Max 2 words unless middle word is 'and'/'or' (then max 3)
        - If 3 words with and/or and not in list remove and/or
        - Hyphens between alphanumeric chars count as two words
        - Cannot start with 3+ digits
        - Each word must be 2+ chars unless it is x or u
        - Removes all non-alphanumeric except spaces and valid hyphens
        - Checks against banned words
        - Makes singular
        - Returns lowercase result
    """   
    if not isinstance(keyword, str):
        keyword = str(keyword)
    
    # Handle internal capitalization before lowercase conversion
    words = keyword.strip().split()
    split_words = []
    for word in words:
        split_words.extend(split_on_internal_capital(word).split())
    keyword = " ".join(split_words)
    
    # Convert to lowercase after handling capitals
    keyword = keyword.lower().strip()
    
    # Remove all non-alphanumeric chars except spaces and hyphens
    keyword = re.sub(r'[^\w\s-]', '', keyword)
    
    # Replace multiple spaces/hyphens with single space/hyphen
    keyword = re.sub(r'\s+', ' ', keyword)
    keyword = re.sub(r'-+', '-', keyword)
    keyword = re.sub(r'_', ' ', keyword)
    
    # For validation, we'll track both original tokens and split words
    tokens = keyword.split()
    words = []
    
    # Validate and collect words for length checking
    for token in tokens:    
        # Handle hyphenated words
        if '-' in token:
            # Check if hyphen is between alphanumeric chars
            if not re.match(r'^[\w]+-[\w]+$', token):
                return None
            # Add hyphenated parts to words list for validation
            parts = token.split('-')
            words.extend(parts)
        else:
            words.append(token)
       
    # Validate word count
    if len(words) > 3:
        return None
    # Enforce two word limit unless connected by and/or
    if len(words) == 3:
        if words[1] not in ['and', 'or']:
            return None
        # Remove and/or and make singular
        if ' '.join(words) in AND_EXCEPTIONS:
            pass
        else:
            tokens = [de_pluralize(words[0]), de_pluralize(words[2])]
            
    # Words are validated and but hypens preserved
    for word in words:
        
        # Check minimum length but allow x-ray or u-turn
        if len(word) < 2 and word not in ['x', 'u']:
            return None
            
        # Check for banned words
        if word in banned_words:
            return None
            
    # Check if starts with 3+ digits
    if re.match(r'^\d{3,}', words[0]):
        return None
        
    # Make solo words singular
    if len(words) == 1:
        tokens = [de_pluralize(words[0])]
        
    # If two words make the second singlular
    else:
        tokens[-1] = de_pluralize(tokens[-1])
        
    # Return the original tokens (preserving hyphens)
    return ' '.join(tokens)
    
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
        
    pattern = re.compile(r'(?i)(keyword|keywords):', re.IGNORECASE)

    match = pattern.search(data)
    if not match:
        return {}

    remaining_string = data[match.end():].strip()
    keywords = []

    if '[' in remaining_string and ']' in remaining_string:
        try:
            list_part = remaining_string[remaining_string.index('['):remaining_string.index(']')+1]
            keywords = eval(list_part)
        except:
            pass
    elif remaining_string.startswith('-'):
        lines = remaining_string.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('-'):
                keywords.append(line[1:].strip())
    else:
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

        try:
            return json.loads(rj(data))
        except:
            pass
        try:
            # first_json will return the first json found in a string
            # repair_json tries to repair json using some heuristics
            return json.loads(rj(first_json(data)))
        except:
            pass    
        try:    
            # Is it a markdown list?
            if result := markdown_list_to_dict(data):
                return result
        except:
            pass
        try:    
            # The nuclear option - wrap whatever it is around brackets and load it
            # Hopefully normalize_keywords will take care of any garbage
            result = json.loads(first_json(rj("{" + data + "}")))
            if result.get("Keywords"):
                return result
        except:
            pass
        try:    
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
        self.update_keywords = False
        self.reprocess_failed = False
        self.reprocess_all = False
        self.reprocess_orphans = True
        self.text_completion = False
        self.gen_count = 150
        self.detailed_caption = False
        self.short_caption = True
        self.skip_verify = False
        self.quick_fail = False
        self.no_caption = False
        self.update_caption = False
        self.caption_instruction = "Describe the image."
        self.system_instruction = "You are a helpful assistant."
        self.instruction = """First, generate a detailed caption for the image.

Next, generate 7 unique one or two word keywords for the image. Include the following when present:

 - Themes, concepts
 - Items, animals, objects
   - Key features, aspects
 - Structures, landmarks, setting
   - Foreground and background elements   
 - Notable colors, textures, styles
 - Actions, activities
 - Human demographics:
   - Physical appearance
   - Age range
   - Apparent ancestry
   - Visible occupation/role
   - Obvious relationships between individuals
   - Clearly conveyed emotions, expressions, body language
   
Limit response to things clearly and obviously apparent; do not guess. Do not combine words. Use ENGLISH only. Generate ONLY a JSON object with the keys Caption and Keywords as follows {"Caption": str, "Keywords": []}"""

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
        ]}
        
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
            "--reprocess-all", action="store_true", help="Reprocess all files"
        )
        parser.add_argument(
            "--reprocess-failed", action="store_true", help="Reprocess failed files"
        )
        parser.add_argument(
            "--reprocess-orphans", action="store_true", help="If a file has a UUID, determine its status"
        )
        parser.add_argument(
            "--update-keywords", action="store_true", help="Update existing keyword metadata"
        )
        parser.add_argument(
            "--gen-count", default=150, help="Number of tokens to generate"
        )
        parser.add_argument("--detailed-caption", action="store_true", help="Write a detailed caption along with keywords")
        parser.add_argument(
            "--skip-verify", action="store_true", help="Skip verifying file metadata validity before processing"
        )
        parser.add_argument("--update-caption", action="store_true", help="Add the generated caption to the existing description tag")
        parser.add_argument("--quick-fail", action="store_true", help="Mark failed after one try")
        parser.add_argument("--short-caption", action="store_true", help="Write a short caption along with keywords")
        parser.add_argument("--no-caption", action="store_true", help="Do not modify caption")
        args = parser.parse_args()

        config = cls()
        for key, value in vars(args).items():
            setattr(config, key, value)
        return config

class LLMProcessor:
    def __init__(self, config):
        self.api_url = config.api_url
        self.config = config
        self.instruction = config.instruction
        self.system_instruction = config.system_instruction
        self.caption_instruction = config.caption_instruction
        config_dict = {
            "max_length": config.gen_count,
            "top_p": 0.95,
            "top_k": 0,
            "temp": 0.3,
            "rep_pen": 1.05,
            "min_p": 0.05,
        }
        self.core = KoboldAPICore(config.api_url, config.api_password, **config_dict)

    def describe_content(self, task="", processed_image=None):
        if not processed_image:
            print("No image to describe.")
            return None
        if task == "caption":
            instruction = self.caption_instruction
        elif task == "keywords":
            instruction = self.instruction
        elif task == "caption_and_keywords":
            instruction = self.instruction
        else:
            print(f"invalid task: {task}")
            return None
        return self.core.wrap_and_generate(instruction = instruction, system_instruction=self.system_instruction, images=[processed_image])

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

    def __init__(self, config, check_paused_or_stopped=None, callback=None):
        self.config = config
        self.llm_processor = LLMProcessor(config)
        
        if check_paused_or_stopped is None:

            self.check_paused_or_stopped = lambda: False
        else:
            self.check_paused_or_stopped = check_paused_or_stopped
            
        if callback is None:
            self.callback = print
        else:
            self.callback = callback
        
        self.files_in_queue = 0
        self.total_processing_time = 0
        self.files_processed = 0
        self.files_completed = 0
        # Multiples of 28 for Qwen-2-VL: 336, 448, 560, 672, 784, 980
        self.image_processor = ImageProcessor(max_dimension=560)
        
        self.et = exiftool.ExifToolHelper(check_execute=False)
        
        # Words in the prompt tend to get repeated back by certain models
        self.banned_words = ["no", "unspecified", "unknown", "standard", "unidentified", "time", "category", "actions", "setting", "objects", "visual", "elements", "activities", "appearance", "professions", "relationships", "identify", "photography", "photographic", "topiary"]
                
        # These are the fields we check. ExifTool returns are kind of strange, not always
        # conforming to where they are or what they actually are named. These should find all of them
        self.keyword_fields = [
            "Keywords",
            "IPTC:Keywords",
            "Composite:keywords",
            "Subject",
            "DC:Subject",
            "XMP:Subject",
            "XMP-dc:Subject"
        ]
        self.caption_fields = [
            "Description",
            "XMP:Description",
            "ImageDescription",
            "DC:Description",
            "EXIF:ImageDescription",
            "Composite:Description",
            "Caption",
            "IPTC:Caption",
            "Composite:Caption"
            "IPTC:Caption-Abstract",
            "XMP-dc:Description",
            "PNG:Description"
        ]

        self.identifier_fields = [
            "Identifier",
            "XMP:Identifier",            
        ]
        self.status_fields = [
            "Status",
            "XMP:Status"
        ]
        
        self.image_extensions = config.image_extensions
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
            None.
        """
        if not file_ext.startswith("."):
            file_ext = "." + file_ext
        file_ext = file_ext.lower()
        for file_type, extensions in self.image_extensions.items():
            if file_ext in [ext.lower() for ext in extensions]:
                return file_type
        return None

    def check_uuid(self, metadata, file_path):
        """ Very important or we end up processing 
            files more than once
        """ 
        try:

            status = metadata.get("XMP:Status")
            identifier = metadata.get("XMP:Identifier")
            keywords = metadata.get("MWG:Keywords")
            caption = metadata.get("MWG:Description")
            
            if identifier and self.config.reprocess_orphans:
                if not status:
                    if keywords:
                        metadata["XMP:Status"] = "success"
                    
                    if not keywords:
                        metadata["XMP:Status"] = "failed" 
                
                    try:
                        written = self.write_metadata(file_path, metadata)
                        if written:
                            print(f"Status added for orphan: {file_path}")  
                            self.callback(f"Status added for orphan: {file_path}")
                        else:
                            print(f"Metadata write error for orphan: {file_path}")
                            self.callback(f"Metadata write error for orphan: {file_path}")
                    except:
                        print("Error writing orphan status")
            # Does file have a UUID in metadata
            if identifier:
               
                if not self.config.reprocess_all and status == "success":
                    return None
                    
                # If it is retry, do it again
                if self.config.reprocess_all or status == "retry":
                    metadata["XMP:Status"] = None
                    return metadata
                
                # If it is fail, don't do it unless we specifically want to
                if status == "failed":
                    if self.config.reprocess_failed or self.config.reprocess_all:
                        metadata["XMP:Status"] = None
                        return metadata                    
                    else:
                        return None
                
                # If there are no keywords, processs it                
                if not keywords:
                    metadata["XMP:Status"] = None
                    return metadata
                
                else:
                    return None
                
            # No UUID, treat as new file
            else:
                metadata["XMP:Identifier"] = str(uuid.uuid4())
                return metadata  # New file

        except Exception as e:
            print(f"Error checking UUID: {str(e)}")
            return None
                        
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
        try:
            while not (self.indexer.indexing_complete and self.metadata_queue.empty()):
                if self.check_pause_stop():
                    return
                
                try:
                    directory, files = self.metadata_queue.get(timeout=1)
                    self.callback(f"Processing directory: {directory}")
                    metadata_list = self._get_metadata_batch(files)
                    
                    for metadata in metadata_list:
                                

                        if metadata:
                            if not self.config.skip_verify:
                                # Check if ExifTool returned any Warnings or Errors. It comes as value "0 0 0"
                                # for number of errors warnings and minor warnings
                                if "ExifTool:Validate" in metadata:
                                    errors, warnings, minor = map(int, metadata.get("ExifTool:Validate", "0 0 0").split())
                                    source_file = metadata.get("SourceFile")
                                    if errors > 0:
                                        print(f"{source_file}: failed to validate. Skipping!")
                                        self.callback(f"\n{source_file}: failed to validate. Skipping!")
                                        self.files_processed +=1
                                        continue
                                                       
                            keywords = []
                            status = None
                            identifier = None
                            caption = None
                            
                            # Make a copy with only the fields we want to write
                            new_metadata = {}
                            new_metadata["SourceFile"] = metadata.get("SourceFile")
                            
                            for key, value in metadata.items():
                            
                                # Collect all keywords
                                if key in self.keyword_fields:
                                    keywords.extend(value)
                            
                                # Ignore any duplicate captions
                                if key in self.caption_fields:
                                    caption = value
                              
                                # Processing fields
                                if key in self.identifier_fields:
                                    identifier = value
                                if key in self.status_fields:
                                    status = value
                                    
                            # Standardize the fields                             
                            if keywords:
                                new_metadata["MWG:Keywords"] = keywords
                            if caption:
                                new_metadata["MWG:Description"] = caption
                            if status:
                                new_metadata["XMP:Status"] = status
                            if identifier:
                                new_metadata["XMP:Identifier"] = identifier
                            self.files_processed += 1
                            self.process_file(new_metadata)

                            
                        if self.check_pause_stop():
                            return
                    
                    self.update_progress()
                    
                except queue.Empty:
                    continue
        finally:
            try:
                self.et.terminate()
                self.callback("ExifTool process terminated cleanly")
            except Exception as e:
                self.callback(f"Warning: ExifTool termination error: {str(e)}")

    def _get_metadata_batch(self, files):
        """Get metadata for a batch of files using persistent ExifTool instance"""
        exiftool_fields = self.keyword_fields + self.caption_fields + self.identifier_fields + self.status_fields 
        
        try:
            if self.config.skip_verify:
                params = []
            else:
                params = ["-validate"]   
            return self.et.get_tags(files, tags=exiftool_fields, params=params)
            
        except Exception as e:
            print("Exiftool error")
            return []

    def update_progress(self):
        files_processed = self.files_processed
        files_remaining = self.indexer.total_files_found - files_processed
        if files_remaining < 0:
            files_remaining = 0
        self.callback(f"Directory processed. Files remaining in queue: {files_remaining}")
        
    def process_file(self, metadata):
        """ Process a single file and update its metadata in one operation.
            This minimizes the number of writes to the file.
        """
        try:    
            file_path = metadata["SourceFile"]
            
            # If the file doesn't exist anymore, skip it
            if not os.path.exists(file_path):
                self.callback(f"File no longer exists: {file_path}")
                return
            
            # Check UUID and status
            metadata = self.check_uuid(metadata, file_path)
            if not metadata:
                return
                
            image_type = self.get_file_type(os.path.splitext(file_path)[1].lower())
            if image_type is None:
                self.callback(f"Not a supported image type: {file_path}")
                return
                
            # Process the file
            start_time = time.time()
            processed_image, image_path = self.image_processor.process_image(file_path)
            updated_metadata = self.generate_metadata(metadata, processed_image)
           
            status = updated_metadata.get("XMP:Status")
            
            # Retry one time if failed
            if not self.config.quick_fail and status == "retry":
                print(f"Retrying {file_path} once")
                updated_metadata = self.generate_metadata(metadata, processed_image)      
                status = updated_metadata.get("XMP:Status")
            
            # If retry didn't work, mark failed
            if not status == "success":
                metadata["XMP:Status"] = "failed"
                if not self.config.dry_run:
                    self.write_metadata(file_path, metadata)
                return
                
            if not self.config.dry_run:
                self.write_metadata(file_path, updated_metadata)
                
            print(f"{file_path}: {status}")
            end_time = time.time()
            processing_time = end_time - start_time
            self.total_processing_time += processing_time
            self.files_completed += 1
            
            # Calculate and display progress info
            in_queue = self.indexer.total_files_found - self.files_processed
            average_time = self.total_processing_time / self.files_completed
            time_left = average_time * in_queue
            time_left_unit = "s"
            
            if time_left > 180:
                time_left = time_left / 60
                time_left_unit = "mins"
            
            if time_left < 0:
                time_left = 0
            
            if in_queue < 0:
                in_queue = 0
            if status == "success":
                self.callback("")    
                self.callback(f"<b>Image:</b> {os.path.basename(file_path)}, <b>Status:</b> {status}")
                
                if updated_metadata.get("MWG:Description"):
                    self.callback(f"<b>Caption:</b> {updated_metadata.get('MWG:Description')}") 
                    self.callback(f"<b>Keywords:</b> {updated_metadata.get('MWG:Keywords', '')}")

                self.callback(
                    f"Processing time: {processing_time:.2f}s Average processing time: {average_time:.2f}s"
                )
                self.callback(
                    f"Processed: {self.files_processed}, In queue: {in_queue}, Time remaining (est): {time_left:.2f}{time_left_unit}"
                )
            if self.check_pause_stop():
                return
            
        except Exception as e:
            self.callback(f"\nError processing: {file_path}: {str(e)}")

            
            return
    
    def generate_metadata(self, metadata, processed_image):
        """ Generate metadata without writing to file.
            Returns (metadata_dict)
            
            short_caption will get a short caption in a single generation
            
            detailed_caption will get get a detailed caption using two
            generations
            
            update_caption appends new caption to existing caption to the existing description.
            
        """
        new_metadata = {}
       
        existing_caption = metadata.get("MWG:Description")
        caption = None
        keywords = None
        detailed_caption = ""
        old_keywords = metadata.get("MWG:Keywords", [])
        file_path = metadata["SourceFile"]
        try:
            # Determine whether to generate caption, keywords, or both
            if not self.config.no_caption and self.config.detailed_caption:
                data = clean_json(self.llm_processor.describe_content(task="keywords", processed_image=processed_image))
                detailed_caption = clean_string(self.llm_processor.describe_content(task="caption", processed_image=processed_image))               
                if existing_caption and self.config.update_caption:
                    caption = existing_caption + "<generated>" + detailed_caption + "</generated>"
                else:
                    caption = detailed_caption
                if isinstance(data, dict):
                    keywords = data.get("Keywords")
                   
            else:
                data = clean_json(self.llm_processor.describe_content(task="caption_and_keywords", processed_image=processed_image))
                         
                if isinstance(data, dict):
                    keywords = data.get("Keywords")
                    if not existing_caption and not self.config.no_caption:
                        caption = data.get("Caption")
                    elif existing_caption and self.config.update_caption:
                        caption = existing_caption + "<generated>" + data.get("Caption") + "</generated>"
                    elif data.get("Caption") and not self.config.no_caption:
                        caption = data.get("Caption")
                    else:
                        caption = existing_caption
                        
            if not keywords:
                status = "retry"
                            
            else:
                status = "success"
                keywords = self.process_keywords(metadata, keywords)

            new_metadata["MWG:Description"] = caption
            new_metadata["MWG:Keywords"] = keywords
            new_metadata["XMP:Status"] = status
            new_metadata["XMP:Identifier"] = metadata.get("XMP:Identifier", str(uuid.uuid4()))
            new_metadata["SourceFile"] = file_path
            return new_metadata
            
        except Exception as e:
            self.callback(f"Parse error for {file_path}: {str(e)}")
            metadata["XMP:Status"] = "retry"
            return metadata
            
    def write_metadata(self, file_path, metadata):
        """Write metadata using persistent ExifTool instance"""
        if self.config.dry_run:
            print("Dry run. Not writing.")
            return True
        try:
            params = ["-P"]
            if self.config.no_backup:
                params.append("-overwrite_original")
                
            # Use existing ExifTool instance
            self.et.set_tags(file_path, tags=metadata, params=params)
            return True
            
        except Exception as e:
            self.callback(f"\nError writing metadata to {file_path}: {str(e)}")
            print(f"\nError writing metadata to {file_path}: {str(e)}")
            return False 
    
    def process_keywords(self, metadata, new_keywords):
        """ Normalize extracted keywords and deduplicate them.
            If update is configured, combine the old and new keywords.
        """
        all_keywords = set()
              
        if self.config.update_keywords:
            existing_keywords = metadata.get("MWG:Keywords", [])
            if isinstance(existing_keywords, str):
                existing_keywords = existing_keywords.split(",").strip()
                
            for keyword in existing_keywords:
                normalized = normalize_keyword(keyword, self.banned_words)
                if normalized:
                    all_keywords.add(normalized)
                           
        for keyword in new_keywords:
            normalized = normalize_keyword(keyword, self.banned_words)
            if normalized:
                all_keywords.add(normalized)
   
        if all_keywords:        
            return list(all_keywords)
        else:
            return None
        
def main(config=None, callback=None, check_paused_or_stopped=None):
    if config is None:
        config = Config.from_args()
             
    file_processor = FileProcessor(
        config, check_paused_or_stopped, callback
    )      
    try:
        file_processor.process_directory(config.directory)
    except Exception as e:
        print(f"An error occurred during processing: {str(e)}")
        if callback:
            callback(f"Error: {str(e)}")
    finally:
        print("Waiting for indexer to complete...")
        file_processor.indexer.join()
        print("Indexing completed.")
   
if __name__ == "__main__":
    main()
