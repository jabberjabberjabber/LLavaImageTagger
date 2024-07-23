import os
import pathlib
import time
from tinydb import TinyDB, Query
import exiftool
import xxhash
import mimetypes
import random
import json
import requests
import base64
from json_repair import repair_json
import re
import argparse

class LLMProcessor:
    def __init__(self, api_url, password):
        self.api_function_urls = {
            'tokencount': '/api/extra/tokencount',
            'interrogate': '/api/v1/generate',
            'max_context_length': '/api/extra/true_max_context_length',
            'check': '/api/generate/check',
            'abort': '/api/extra/abort',
            'version': '/api/extra/version',
            'model': '/api/v1/model',
            'generate': '/api/v1/generate'
        }
        self.image_instruction = 'What do you see in the image? Be specific and descriptive'
        self.metadata_instruction = 'The following caption and metadata was given for an image. Use that to determine the title, keyword tags, summary, and suggest an appropriate filename if the current one is generic. Return as JSON object with keys Title, Tags, Summary, and NewFilename.\n' 
        self.api_url = api_url
        self.password = password
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {password}'
        }
        self.genkey = self._create_genkey()
        
        self.templates = {
            1: {"name": "Alpaca","user": "\n### Instruction:\n","assistant": "\n### Response:\n"},
            2: {"name": "Vicuna", "user": "\nUSER: ", "assistant": "\nASSISTANT: "},
            3: {"name": "Llama 2","user": "[INST] ","assistant": " [/INST]"},
            4: {"name": "Llama 3","user": "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n","assistant": "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"},
            5: {"name": "Phi-3","user": "<|end|><|user|>\n","assistant": "<|end|>\n<|assistant|>"},
            6: {"name": "Mistral","user": "\n[INST] ","assistant": " [/INST]\n"}
	}
        
        self.model = self._get_model()
        self.max_context = self._get_max_context_length()

    def _call_api(self, api_function, payload=None):
        if api_function not in self.api_function_urls:
            raise ValueError(f"Invalid API function: {api_function}")

        url = f"{self.api_url}{self.api_function_urls[api_function]}"

        try:
            if api_function in ['tokencount', 'generate', 'check', 'interrogate']:
                response = requests.post(url, json=payload, headers=self.headers)
                result = response.json()
                if api_function == 'tokencount':
                    
                    return int(result.get('value'))
                else:    
                    return result['results'][0].get('text')              
            else:
                response = requests.get(url, json=payload, headers=self.headers)
                result = response.json()
                return result.get('result', None)
                

        except requests.RequestException as e:
            print(f"Error calling API: {str(e)}")
            return None
        
    def interrogate_image(self, image_path):
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        prompt = self.get_prompt(self.image_instruction, content="")
        payload = {
            'prompt': prompt,
            'images': [base64_image],
            'max_length': 150,
            'genkey': self.genkey,
            'model': 'clip',
            'temperature': 0.1
        }
        
        return clean_string(self._call_api('interrogate', payload))
    
    def describe_content(self, content, instruction):
        prompt = self.get_prompt(instruction, content)        
        payload = {
            'prompt': prompt,
            'max_length': 256,
            'genkey': self.genkey,
            'top_p': 1,
            'top_k': 0,
            'temp': 0.5,
            'rep_pen': 1,
            'min_p': 0.05
        }
        
        return self._call_api('generate', payload)

    def _get_model(self):
        model_name = self._call_api('model')
        if not model_name:
            return None

        def normalize(s):
            return re.sub(r'[^a-z0-9]', '', s.lower())

        normalized_model_name = normalize(model_name.lower())

        matched_template = max(
            ((template, len(normalize(template['name'])))
             for template in self.templates.values()
             if normalize(template['name']) in normalized_model_name),
            key=lambda x: x[1],
            default=(None, 0)
        )[0]

        return matched_template if matched_template else self.templates[1] 
    
    def get_prompt(self, instruction="", content=""):
        user_part = self.model['user']
        assistant_part = self.model['assistant']
        
        return f"{user_part}{instruction}{content}{assistant_part}"
        
    
    @staticmethod
    def _create_genkey():
        return f"KCP{''.join(str(random.randint(0, 9)) for _ in range(4))}"
    

    def _get_max_context_length(self):
         return self._call_api('max_context_length')
         
    def _get_token_count(self, content):
        payload = {'prompt': content, 'genkey': self.genkey}
        return self._call_api('tokencount', payload)
    
def clean_content(content):
    if content is None:
        return ""
    content = ftfy.fix_text(content)
    content = re.sub(r'\n+', '\n', content)
    content = re.sub(r' +', ' ', content)
    return content.strip()

def clean_string(data):
    
    if isinstance(data, dict):
        data = json.dumps(data)
    if isinstance(data, str):
        data = re.sub(r'\n', '', data)
        data = re.sub(r'["""]', '"', data)
        data = re.sub(r'\\{2}', '', data)
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
    pattern = r'```json\s*(.*?)\s*```'
    match = re.search(pattern, data, re.DOTALL)

    if match:
        json_str = match.group(1).strip()
        data = json_str
    else:
        json_str = re.search(r'\{.*\}', data, re.DOTALL)
        if json_str:
            data = json_str.group(0)
        
    data = re.sub(r'\n', ' ', data)
    data = re.sub(r'["""]', '"', data)

    try:
        return json.loads(repair_json(data))
    except json.JSONDecodeError:
        print("JSON error")
        return data
        
class FileProcessor:
    CATEGORY_MAPPINGS = {
        'document': ['.doc', '.docx', '.pdf', '.txt', '.rtf', '.odt'],
        'spreadsheet': ['.xls', '.xlsx', '.csv', '.ods'],
        'presentation': ['.ppt', '.pptx', '.odp'],
        'image': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.svg'],
        'code': ['.py', '.java', '.cpp', '.h', '.js', '.cs', '.rb', '.go', '.swift'],
        'configuration': ['.ini', '.cfg', '.conf', '.json', '.xml', '.yaml', '.yml'],
    }

    def __init__(self, llm_processor):
        self.llm_processor = llm_processor
    
    def update_xmp_tags(self, file_path, llm_metadata):
        try:
            with exiftool.ExifToolHelper() as et:
                xmp_metadata = {}

                if 'Summary' in llm_metadata:
                    xmp_metadata['XMP:Description'] = llm_metadata['Summary']

                if 'Title' in llm_metadata:
                    xmp_metadata['XMP:Title'] = llm_metadata['Title']

                if llm_metadata['Tags']:
                    xmp_metadata['XMP:Tags'] = llm_metadata['Tags']
                    
                if llm_metadata['Keywords']:
                    xmp_metadata['XMP:Tags'] = llm_metadata['Keywords']
                
                if llm_metadata['Keyword Tags']:
                    xmp_metadata['XMP:Tages'] = llm_metadata['Keyword Tags']
                    
                et.set_tags(file_path, xmp_metadata)
            print(f"Updated XMP tags for {file_path}")
        except Exception as e:
            print(f"Error updating XMP tags for {file_path}: {str(e)}")

    def process_file(self, file_path, category, exif_metadata):
        if category == 'image':
            caption = clean_string(self.llm_processor.interrogate_image(file_path))
            description = self.create_metadata_prompt(exif_metadata, caption)    
            instruction = self.llm_processor.metadata_instruction + description
            llm_metadata = clean_json(self.llm_processor.describe_content(caption, instruction))
            #for item in llm_metadata.items()
            
            self.update_xmp_tags(file_path, llm_metadata)
            
            return {"llm_metadata": llm_metadata}
        
        else:
            return {}
    
    def extract_basic_metadata(self, file_path, root_dir):
        path = pathlib.Path(file_path)
        stats = path.stat()
        
        return {
            "filename": path.name,
            "relative_path": str(path.relative_to(root_dir)),
            "size": stats.st_size,
            "created": time.ctime(stats.st_ctime),
            "modified": time.ctime(stats.st_mtime),
            "extension": path.suffix.lower(),
            "category": self._determine_category(path.suffix.lower()),
            "file_hash": self._calculate_file_hash(file_path)
        }

    def _determine_category(self, extension):
        return next((category for category, extensions in self.CATEGORY_MAPPINGS.items() 
                     if extension in extensions), "unknown")

    @staticmethod
    def _calculate_file_hash(file_path):
        xxh = xxhash.xxh64()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                xxh.update(chunk)
        return xxh.hexdigest()

    def extract_exif_metadata(self, file_path):
        try:
            with exiftool.ExifToolHelper() as et:
                metadata = et.get_metadata(file_path)[0]
                return {"exif_metadata": {k: v for k, v in metadata.items() 
                                          if not isinstance(v, (bytes, bytearray)) and len(str(v)) < 1000}}
        except Exception as e:
            print(f"ExifTool extraction failed for {file_path}: {str(e)}")
            return {}
    
    def create_metadata_prompt(self, exif_metadata, caption):
        prompt = ""
        
        if caption:
            prompt += f"\nCaption: {caption}\n\n"
        
        prompt += "Metadata:\n"
        
        for key, value in exif_metadata.get("exif_metadata", {}).items():
            prompt += f"{key} is {value}\n "
        
        prompt = prompt.rstrip(", ")
        
        return prompt
        
class DatabaseHandler:
    def __init__(self, db_path):
        self.db = TinyDB(db_path)

    def insert_or_update(self, metadata):
        File = Query()
        self.db.upsert(metadata, File.relative_path == metadata["relative_path"])

    def file_needs_update(self, file_path, file_mtime):
        File = Query()
        relative_path = str(pathlib.Path(file_path))
        
        result = self.db.search(File.relative_path == os.path.basename(relative_path))
        
        if not result:
            return True 
        
        return False
        #stored_mtime = time.mktime(time.strptime(result[0]['modified']))
        #return file_mtime > stored_mtime


class IndexManager:
    def __init__(self, root_dir, db_path, llm_processor, recursive=True):
        self.root_dir = root_dir
        self.db_handler = DatabaseHandler(db_path)
        self.file_processor = FileProcessor(llm_processor)
        self.recursive = recursive

    def crawl_directory(self):
        if self.recursive:
            for dirpath, _, filenames in os.walk(self.root_dir):
                for filename in filenames:
                    yield os.path.join(dirpath, filename)
        else:
            for filename in os.listdir(self.root_dir):
                file_path = os.path.join(self.root_dir, filename)
                if os.path.isfile(file_path):
                    yield file_path

    def index_files(self, force_rehash=False):
        for file_path in self.crawl_directory():
            file_mtime = os.path.getmtime(file_path)
            
            if force_rehash or self.db_handler.file_needs_update(file_path, file_mtime):
                basic_metadata = self.file_processor.extract_basic_metadata(file_path, self.root_dir)
                category = basic_metadata['category']
                
                if category in ['image']:
                    exif_metadata = self.file_processor.extract_exif_metadata(file_path)
                    processed_metadata = self.file_processor.process_file(file_path, category, exif_metadata)
                    
                    combined_metadata = {**basic_metadata, **exif_metadata, **processed_metadata}
                    self.db_handler.insert_or_update(combined_metadata)
                    
                    yield combined_metadata
                else:
                    print(f"Skipped: {os.path.basename(file_path)}, unsupported category.")
            else:
                print(f"Skipped: {os.path.basename(file_path)}, already indexed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Image Indexer")
    parser.add_argument("directory", help="Directory containing the files")
    parser.add_argument("--api-url", default="http://localhost:5001", help="URL for the LLM API")
    parser.add_argument("--api-password", default="", help="Password for the LLM API")
    parser.add_argument("--no-crawl", action="store_true", help="Disable recursive indexing")
    parser.add_argument("--force-rehash", action="store_true", help="Force rehashing of all files")
    
    args = parser.parse_args()

    API_URL = args.api_url
    API_PASSWORD = args.api_password
    root_directory = args.directory
    db_file = os.path.join(root_directory, "filedata.json")
    force_rehash = args.force_rehash
    recursive = not args.no_crawl

    llm_processor = LLMProcessor(API_URL, API_PASSWORD)
    index_manager = IndexManager(root_directory, db_file, llm_processor, recursive)

    try:
        for metadata in index_manager.index_files(force_rehash):
            print(f"Indexed: {metadata['filename']} (Category: {metadata['category']}, Hash: {metadata['file_hash']})")
            if 'llm_metadata' in metadata:
                print(f"LLM Metadata: {metadata['llm_metadata']}")

    except Exception as e:
        print(f"An error occurred: {str(e)}")