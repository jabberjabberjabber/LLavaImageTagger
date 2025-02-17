import os, json, time, re, argparse, exiftool, threading, queue, calendar, io, uuid

from tinydb import TinyDB, where, Query
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
        self.overwrite_keywords = False
        self.update_keywords = False
        self.reprocess_failed = False
        self.reprocess_all = False
        self.reprocess_orphans = False
        self.text_completion = False
        self.gen_count = 350
        self.write_caption = False
        self.overwrite_caption = True
        self.caption_instruction = "Describe the image in detail. Be specific."
        self.system_instruction = "You are a helpful assistant."
        self.instruction = """Your task is to first generate a detailed description for the image. If a description is included with the image, use that one.

Next, generate at least 10 unique Keywords for the image. Include:

 - Actions
 - Setting, location and background
 - Items and structures
 - Colors and textures
 - Composition, framing
 - Photographic style 
 - If there is one or more person:
   - Subjects
   - Physical appearance
   - Clothing
   - Gender
   - Age
   - Professions
   - Relationships 


Provide one word per entry; if more than one word is required split into two entries. Do not combine words. Generate ONLY a JSON object with the keys Caption and Keywords as follows {"Caption": str, "Keywords": [list]}"""

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
            "--reprocess-orphans", action="store_true", help="If a file has a UUID and keywords but is not in the database, skip processing it"
        )
        parser.add_argument(
            "--update-keywords", action="store_true", help="Update existing keyword metadata"
        )
        parser.add_argument(
            "--gen-count", default=150, help="Number of tokens to generate"
        )
        parser.add_argument("--write-description", action="store_true", help="Write description")
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
        self.image_processor = ImageProcessor(max_dimension=1344)
        config_dict = {
            "max_length": config.gen_count,
            "top_p": 1,
            "top_k": 40,
            "temp": 0.3,
            "rep_pen": 1.05,
            "min_p": 0,
        }
        self.core = KoboldAPICore(config.api_url, config.api_password, config_dict)

    def describe_content(self, file_path, task="keywords", caption=""):
        if task == "keywords":
            instruction = self.instruction
        elif task == "caption":
            instruction = self.caption_instruction
        elif task == "keywords_with_caption":
            instruction = "Included description: \n" + caption + "\n\n" + self.instruction
        else:
            print(f"Invalid task")
            return None
        encoded_image, path = self.image_processor.process_image(file_path)
        return self.core.wrap_and_generate(instruction=instruction, images=[encoded_image])

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
    def __init__(self, config, check_paused_or_stopped, callback):
        self.config = config
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
        self.banned_words = ["action", "no", "unspecified", "perspective", "unknown", "standard", "unindentified", "type", "time", "category", "actions", "setting", "objects", "visual", "composition", "structures", "elements", "activities", "appearance", "gender", "professions", "relationships", "identify", "photography", "photographic", "background", 'color', "texture"]
                
        # These are the fields we check. ExifTool returns are kind of strange, not always
        # conforming to where they are or what they actually are named
        self.exiftool_fields = [
            "MWG:Keywords",
            "XMP:Identifier",
            "XMP:Subject",
            "Keywords",
        ]
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
        """ Very important or we end up with multiple
            DB entries or reprocess files for no reason
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
                    print(f"{file_path} skipped.")
                    return None 
                
                # Orphan -- has UUID and Keywords but not in db
                if self.config.reprocess_orphans and are_keywords:
                    print(f"{file_path} skipped.") 
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
                            print(f"{file_path} skipped.")
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
                        # Check if ExifTool returned any Warnings or Errors. It comes as value "0 0 0"
                        # for number of errors warnings and minor warnings
                        errors, warnings, minor = map(int, metadata.get("ExifTool:Validate").split())
                        if errors > 0 or (warnings > 0 and warnings != minor):
                            print(f"{metadata.get("SourceFile")}: failed to validate. Skipping!")
                            self.callback(f"----\n{metadata.get("SourceFile")}: failed to validate. Skipping!")
                            continue
                        keywords = metadata.get("Keywords", [])
                        if metadata.get("Composite:Keywords"):
                            keywords += metadata.get("Composite:Keywords")
                        if metadata.get("Subject"):
                            keywords += metadata.get("Subject")
                        if metadata.get("IPTC:Keywords"):
                            keywords += metadata.get("IPTC:Keywords")
                        if metadata.get("MWG:Keywords"):
                            keywords += metadata.get("MWG:Keywords")                            
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
        with exiftool.ExifToolHelper(check_execute=False) as et:  
            return et.get_tags(files, self.exiftool_fields, "-validate")         

    def update_progress(self):
        files_processed = self.files_processed
        files_remaining = self.indexer.total_files_found - files_processed
        if files_remaining < 0:
            files_remaining = 0
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
                    return
                else:
                    metadata = metadata_added
            image_type = self.get_file_type(os.path.splitext(file_path)[1].lower())

            if image_type is not None:
                start_time = time.time()
                if self.config.write_caption:
                    caption = clean_string(
                        self.llm_processor.describe_content(
                            file_path, task="caption"
                        )
                    )
                    if caption:
                        metadata["Description"] = caption
                metadata = self.update_metadata(metadata, file_path)
                
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
                    
                    if time_left < 0:
                        time_left = 0
                    
                    if in_queue < 0:
                        in_queue = 0
                    
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
                    print(f"Metadata creation failed for {file_path}")
                    return
                
                elif metadata.get("status") == "retry":
                    print(f"Retrying metadata creation for {file_path}")
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
        
        # Handle existing keywords if updating
        
        if self.config.update_keywords:
            existing_keywords = metadata.get("Keywords", [])
            
            # Handle case where Keywords is a string instead of list
            if isinstance(existing_keywords, str):
                existing_keywords = [existing_keywords]
            elif not isinstance(existing_keywords, list):
                existing_keywords = []
                
            for keyword in existing_keywords:
                # Make sure keywords conform to our structure
                normalized = normalize_keyword(keyword, self.banned_words)
                if normalized:
                    all_keywords.add(normalized)
                    
        # Process new keywords from LLM
        extracted_keywords = self.extract_values(llm_metadata.get("Keywords", []))
        
        if extracted_keywords:
            # Make sure keywords conform to our structure
            for keyword in extracted_keywords:
                normalized = normalize_keyword(keyword, self.banned_words)
                if normalized:
                    all_keywords.add(normalized)
       
        if all_keywords:        
            return list(all_keywords)
        else:
            return None
    
    def update_metadata(self, metadata, file_path):
        """ First query the LLM, fix the inevitably malformed JSON,
            check to see if there is a dict with value Keywords. Put them
            in, clearing other keyword fields. If it fails any part, mark retry
            and try again. Another fail gets marked as fail. exiftool helper
            is called at the end to put the metdata in.
        """
        file_path = metadata["SourceFile"]
        
        try:
            # Is there an existing caption? If so, use it with the image
            if metadata.get("Description"):
                llm_metadata = clean_json(self.llm_processor.describe_content(file_path, task="keywords_with_caption", caption=metadata.get("Description")))
            else:
                llm_metadata = clean_json(self.llm_processor.describe_content(file_path, task="keywords"))
            
            # Check if the json got parsed and Keywords is a key
            if llm_metadata["Keywords"] or llm_metadata["keywords"]:
                xmp_metadata = {}
                
                # If detailed caption was generated, use that 
                if metadata.get("Description") and self.config.write_caption:
                    xmp_metadata["XMP:Description"] = metadata["Description"]
                
                # If replace is set, use caption in keywords dict if exists
                elif not self.config.update_keywords:
                    xmp_metadata["XMP:Description"] = llm_metadata.get("Caption")
                xmp_metadata["XMP:Identifier"] = metadata.get(
                    "XMP:Identifier", str(uuid.uuid4())
                )
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
            print(f"Parse error for {file_path}.")
            if metadata.get("status") == "retry" or metadata.get("status") == "failed":
                metadata["status"] = "failed"
                self.callback(f"\n---\nParse error for {file_path}, it has been marked as failed.")
            else:
                metadata["status"] = "retry"
            return metadata

        if self.config.dry_run:
            self.callback(f"{output}\nSuccess, but nothing written in pretend mode.\n")
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
                    self.callback(f"\n---\nParse error for {file_path}, it has been marked as failed.")
                else:
                    metadata["status"] = "retry"
                return metadata

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
