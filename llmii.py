import os
import logging
import argparse
import exiftool
import requests
import base64
from PIL import Image
import io
import random
import re
from json_repair import repair_json
import json
import time
import rawpy

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
        return ""
    if isinstance(data, dict):
        data = json.dumps(data)
        try:
            return json.loads(data)
        except:
            pass
    pattern = r"```json\s*(.*?)\s*```"
    match = re.search(pattern, data, re.DOTALL)

    if match:
        json_str = match.group(1).strip()
        data = json_str
    else:
        json_str = re.search(r"\{.*\}", data, re.DOTALL)
        if json_str:
            data = json_str.group(0)

    data = re.sub(r"\n", " ", data)
    data = re.sub(r'["""]', '"', data)

    try:
        return json.loads(repair_json(data))
    except json.JSONDecodeError:
        print("JSON error")
    return data
    
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
        self.write_caption = False
        self.image_instruction = "What do you see in the image? Be specific and descriptive"
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
        parser.add_argument("--update-keywords", action="store_true", help="Update Keywords metadata")
        parser.add_argument("--write-caption", action="store_true", help="Write caption metadata")
        parser.add_argument("--keywords-count", type=int, default=7, help="Number of keywords to generate")
        parser.add_argument("--image-instruction", default="What do you see in the image? Be specific and descriptive", help="Custom instruction for image description")
        parser.add_argument("--max-workers", type=int, default=4, help="Maximum number of worker threads")
        args = parser.parse_args()
        
        config = cls()
        for key, value in vars(args).items():
            setattr(config, key, value)
        return config
        
class ImageProcessor:
    """ The CLIP in the LLM takes a base64 encoded image. It needs
        an RGB JPEG or PNG file. If the image isn't one of these,
        we try to extract a JPEG and if there isn't one we
        just convert it to a JPEG and put that in a buffer and discard
        it when we are done.
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def route_image(self, file_path, is_camera_raw):
        try:
            if is_camera_raw:
                return self.raw_to_base64_jpeg(file_path)     
        
        except Exception as e:
            self.logger.error(f"Image is raw but unsupported {file_path}: {str(e)}")
        
        return self.process_image(file_path)
    
    def process_image(self, file_path):
        try:
            with Image.open(file_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                jpeg_bytes = io.BytesIO()
                img.save(jpeg_bytes, format='JPEG', quality=95)
                jpeg_bytes.seek(0)
                base64_encoded = base64.b64encode(jpeg_bytes.getvalue()).decode('utf-8')
            
            return base64_encoded

        except Exception as e:
            self.logger.error(f"Error processing image: {str(e)}")
            return None
    
    def raw_to_base64_jpeg(self, file_path):
        try:
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess()
            img = Image.fromarray(rgb)
            jpeg_bytes = io.BytesIO()
            img.save(jpeg_bytes, format='JPEG', quality=95)
            jpeg_bytes.seek(0)
            base64_encoded = base64.b64encode(jpeg_bytes.getvalue()).decode('utf-8')
            return base64_encoded
        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {str(e)}")
            return None

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
        self.image_instruction = config.image_instruction
        
        # this prompt works well, you can change it if you want, but comment it out in
        # case you want to use it again.
        self.metadata_instruction = f"Use the metadata and caption to generate a summary and no fewer than {self.config.keywords_count} IPTC keywords. Return as a JSON object with keys Summary and Keywords.\n"
        
        self.api_url = config.api_url
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_password}",
        }
        self.genkey = self._create_genkey()
        
        # you may have to add an entry name for a finetune with
        # a different name than its base
        self.templates = {
            1: {"name": "Alpaca", "user": "\n\n### Instruction:\n\n", "assistant": "\n\n### Response:\n\n", "system": ""},
            2: {"name": ["Vicuna", "Wizard", "ShareGPT", "Qwen"], "user": "### Human: ", "assistant": "\n### Assistant: ", "system": ""},
            3: {"name": ["Llama 2", "Llama2", "Llamav2"], "user": "[INST] ", "assistant": " [/INST]", "system": ""},
            4: {"name": ["Llama 3", "Llama3", "Llama-3"], "endTurn": "<|eot_id|>", "system": "", "user": "<|start_header_id|>user<|end_header_id|>\n\n", "assistant": "<|start_header_id|>assistant<|end_header_id|>\n\n"},
            5: {"name": "Phi-3", "user": "<|end|><|user|>\n", "assistant": "<end_of_turn><|end|><|assistant|>\n", "system": ""},
            6: {"name": ["Mistral", "bakllava"], "user": "\n[INST] ", "assistant": " [/INST]\n", "system": ""},
            7: {"name": ["Yi"], "user": "<|user|>", "assistant": "<|assistant|>", "system": ""},
            8: {"name": ["ChatML", "obsidian", "Nous", "Hermes", "llava-v1.6-34b"], "user": "<|im_start|>user\n", "assistant": "<|im_end|>\n<|im_start|>assistant\n", "system": ""},
            9: {"name": ["WizardLM"], "user": "input:\n", "assistant": "output\n", "system": ""}
        }
        self.model = self._get_model()
        self.max_context = self._get_max_context_length()

    def _call_api(self, api_function, payload=None):
        """ The magic part where we talk to koboldAPI. Open the browser
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

    def interrogate_image(self, base64_image):       
        """ Changing these sampler settings is not recommended.
        """         
        prompt = self.get_prompt(self.image_instruction)
        payload = {
            "prompt": prompt,
            "images": [base64_image],
            "max_length": 150,
            "genkey": self.genkey,
            "model": "clip",
            "temperature": 0.1,
        }
        return self._call_api("interrogate", payload)

    def describe_content(self, metadata, caption):
        """ You can play with the sampler settings to achieve 
            different results.
            Max length gets expanded as keyword number increases
            to compensate for longer generation.
        """
        prompt = self.metadata_prompt(metadata, caption)
        payload = {
            "prompt": prompt,
            "max_length": 200 + (self.config.keywords_count * 15),
            "genkey": self.genkey,
            "top_p": 1,
            "top_k": 0,
            "temp": 0.5,
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
    
    def metadata_prompt(self, metadata, caption):
        """ Creates the portion of the second query which contains the 
            metadata to give the LLM information with which to come 
            up with the tags.
            Start with the caption we got from first query and append
            existing tags except in the case we want to redo them.
        """
        prompt = f"Caption: {caption}\n"
        if isinstance(metadata, dict):
            no_key = ["caption"]
            if self.config.write_keywords:
                no_key.append("XMP:Subject")
                no_key.append("IPTC:Keywords")
                no_key.append("MWG:Keywords")    
            prompt += "Metadata:\n"
            for key, value in metadata.items():
                if key not in no_key:
                    prompt += f"{key} is {value}\n"
        return self.get_prompt(instruction=self.metadata_instruction, content=prompt)
    
    def get_prompt(self, instruction="", content=""):
        """ Uses the instruct templates to create a prompt with the proper 
            start and end sequences. If the model name does not contain
            the name of the model it was based on, these may be incorrect.
        """
        user_part = self.model["user"]
        assistant_part = self.model["assistant"]
        end_part = self.model.get("endTurn", "")
        prompt = f"{user_part}{instruction}{content}{end_part}{assistant_part}"
        #print(f"Querying LLM with prompt:\n{prompt}")
        return prompt

    @staticmethod
    def _create_genkey():
        """ Prevents kobold from returning your generation to another 
            query.
        """
        return f"KCPP{''.join(str(random.randint(0, 9)) for _ in range(4))}"
    
    #unused by the script but functional
    def _get_max_context_length(self):
        return self._call_api("max_context_length")

    #unused by the script but functional
    def _get_token_count(self, content):
        payload = {"prompt": content, "genkey": self.genkey}
        return self._call_api("tokencount", payload)

class FileProcessor:
    def __init__(self, config, image_processor, check_paused_or_stopped, callback):
        self.config = config
        self.image_processor = image_processor
        self.llm_processor = LLMProcessor(config)
        self.logger = logging.getLogger(__name__)
        self.check_paused_or_stopped = check_paused_or_stopped
        self.callback = callback
        self.files_in_queue = 0
        self.files_done = 1
        
        # add more tags here if needed
        self.exiftool_fields = [
            "FileName", "Directory", "FileType", "MIMEType",
            "DateTimeOriginal", "Caption-abstract", "UserComments",
            "CreateDate", "ModifyDate", "XMP:Description", "Title",
            "Subject", "Keywords", "Make", "Model",
            "LensModel", "Artist", "Copyright", "JPGFromRaw",
        ]
        
        # add more extensions here if needed
        self.file_extensions = {
            ".arw", ".cr2", ".dng", ".gif", ".jpeg", ".tif", ".tiff",
            ".jpg", ".nef", ".orf", ".pef", ".png", ".raf", ".rw2", ".srw"
            }
        
        self.raw_extensions = {
            ".arw", ".cr2", ".dng", ".nef", ".orf", ".pef", ".raf", ".rw2", ".srw"
            }
        # untested:
        # arq, crm, cr3, crw, ciff, erf, fff, flif, gpr, hdp, wdp,
        # heif, hif, iiq, insp, jpf, jpm, jpx, jph, mef, mos, mpo,
        # nrw, ori, jng, mng, qtif, qti, qif, sr2, x3f
                
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
                file_extension = os.path.splitext(filename)[1].lower()
                if file_extension in self.file_extensions:
                    files.append(file_path)
        if files:
            self.files_in_queue += len(files) 
            self.callback(f"Added folder {directory} to queue containing {len(files)} image files.")
        return files
        
    def process_directory(self, directory):
        logging.basicConfig(level=logging.DEBUG)
        files = self.list_files(directory)
        metadata_list = []
        try:
            with exiftool.ExifToolHelper(logger=logging.getLogger(__name__)) as et:
                metadata_list = et.get_tags(files, self.exiftool_fields)
        except Exception as e:
            self.logger.error(f"Error processing directory {directory}: {str(e)}")
        for metadata in metadata_list:
            if self.check_pause_stop():
                return
            self.process_file(metadata)
        
    
    def process_file(self, metadata):
        self.files_left = abs(self.files_done - self.files_in_queue)
        try:
            file_path = metadata['SourceFile']
            file_extension = os.path.splitext(file_path)[1].lower()
            
            if file_extension in self.file_extensions:
                is_camera_raw = file_extension in self.raw_extensions
                
                image_object_or_path = self.image_processor.route_image(file_path, is_camera_raw)
            
                if self.check_pause_stop():
                    return
            
                if image_object_or_path:
                    self.update_metadata(metadata, image_object_or_path)
                    self.files_done += 1
            else:
                self.callback(f"Not a supported image type: {file_path}")
                
        except Exception as e:
            self.logger.error(f"Error processing file {metadata.get('FileName', 'unknown')}: {str(e)}")
        
    def process_keywords(self, metadata, llm_metadata):
        """ Check if update is configured, if so combine the old and new
            keywords into a set to deduplicate them 
        """
        all_keywords = set(llm_metadata.get("Keywords", []))
        
        if self.config.update_keywords:
            keywords = metadata.get("IPTC:Keywords", [])
            subject = metadata.get("XMP:Subject", [])
            all_keywords.update(subject)
            all_keywords.update(keywords)
        return list(all_keywords)
    
    def update_metadata(self, metadata, base64_image):
        """ clean_string and clean_json are vital here to ensure useable output
            from the LLM. If they are ommitted we will not get a json object and
            everything will break.
            We query the LLM twice. Once with the image asking for a description,
            and a second time with the description and the metadata asking
            for a JSON object.
        """        
        try:
            file_path = metadata["SourceFile"]
            
            output = f"---\nImage: {os.path.basename(file_path)}" 
            
            caption = clean_string(self.llm_processor.interrogate_image(base64_image))
            llm_metadata = clean_json(self.llm_processor.describe_content(metadata, caption))
            
            with exiftool.ExifToolHelper() as et:
                xmp_metadata = {}        
                
                if llm_metadata["Keywords"]:
                    xmp_metadata["IPTC:Keywords"] = ""
                    xmp_metadata["XMP:Subject"] = ""
                    xmp_metadata["MWG:Keywords"] = self.process_keywords(metadata, llm_metadata)
                    output += "\nKeywords: " + " ,".join(xmp_metadata["MWG:Keywords"])
        
                # MWG is metadata working group. This will sync the tags across
                # EXIF, IPTC, and XMP
                if self.config.write_caption and llm_metadata['Summary']:
                    xmp_metadata["MWG:Description"] = llm_metadata["Summary"]
                    output += "\nDescription: " + xmp_metadata["MWG:Description"]
                     
                if not self.config.dry_run:
                    if self.config.overwrite:
                        et.set_tags(
                            file_path,
                            tags=xmp_metadata,
                            params=["-P", "-overwrite_original"],
                        )
                    else:
                        et.set_tags(file_path, tags=xmp_metadata)

                    self.callback(f"{output}\n---\nCompleted {self.files_done} so far with {self.files_left} remaining to be processed in folder queue.")
                else:
                    self.callback(f"{output}\n---\nCompleted {self.files_done} so far with {self.files_left} remaining to be processed in folder queue.")
                
        except Exception as e:
            self.logger.error(f"Error updating metadata for {metadata.get('SourceFile', 'unknown')}: {str(e)}")
        
def main(config=None, callback=None, check_paused_or_stopped=None):
    if config is None:
        config = Config.from_args()
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    logger.info("Initializing components...")
    image_processor = ImageProcessor()
    
    file_processor = FileProcessor(config, image_processor, check_paused_or_stopped, callback)

    if config.no_crawl:
        try:
            file_processor.process_directory(config.directory)
            
        except Exception as e:
            logger.error(f"An error occurred during processing: {str(e)}")
            if callback:
                callback(f"Error: {str(e)}")
    else:
        directories = [root for root, _, _ in os.walk(config.directory)]
        
        for directory in directories:
            if check_paused_or_stopped and check_paused_or_stopped():
                logger.info("Processing stopped by user.")
                break
            try:
                file_processor.process_directory(directory)
            except:
                pass


if __name__ == "__main__":
    main()
