import base64
import io 
import math
import os
from pathlib import Path
from typing import Optional, Tuple, Union, List
import rawpy
from PIL import Image
from pillow_heif import register_heif_opener

class ImageProcessor:
    def __init__(self, max_dimension: int = 1024,
                 patch_sizes: Optional[List[int]] = None,
                 max_file_size: int = 50 * 1024 * 1024):
        
        if max_dimension <= 0:
            raise ValueError("max_dimension must be positive")
        self.max_dimension = max_dimension
        self.max_file_size = max_file_size
        self.patch_sizes = patch_sizes or [8, 14, 16, 32]
        self.lcm = math.lcm(*self.patch_sizes)
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
    def _get_image_type(self, file_path):
        """ Return the image type based on extension
        """
        file_ext = os.path.splitext(file_path)[1]
        if not file_ext.startswith("."):
            file_ext = "." + file_ext
        file_ext = file_ext.lower()
        for file_type, extensions in self.image_extensions.items():
            if file_ext in [ext.lower() for ext in extensions]:
                return file_type
        return None
    
    def _calculate_dimensions(self, width: int, height: int) -> Tuple[int, int]:
        """ Calculate dimensions maintaining aspect ratio and patch compatibility 
        """
        scale = min(self.max_dimension / width, self.max_dimension / height)
        
        scaled_width = width * scale
        scaled_height = height * scale
        
        new_width = math.ceil(scaled_width / self.lcm) * self.lcm
        new_height = math.ceil(scaled_height / self.lcm) * self.lcm
        
        return new_width, new_height

    def _resize_image(self, img: Image.Image) -> Image.Image:
        """ Resize image ensuring patch compatibility
        """
        new_width, new_height = self._calculate_dimensions(*img.size)
        if new_width != img.width or new_height != img.height:
            return img.resize((new_width, new_height), Image.Resampling.BICUBIC)
        return img

    def process_raw_image(self, file_path: Union[str, Path]) -> str:
        """ Process RAW image files
        """
        with rawpy.imread(str(file_path)) as raw:
            try:
                # Try to extract embedded JPEG thumbnail first
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    thumb_img = Image.open(io.BytesIO(thumb.data))
                    resized = self._resize_image(thumb_img)
                    buffer = io.BytesIO()
                    resized.save(buffer, format="JPEG", quality=95)
                    return base64.b64encode(buffer.getvalue()).decode()
            except:
                pass

            rgb = raw.postprocess()
            img = Image.fromarray(rgb)
            resized = self._resize_image(img)
            buffer = io.BytesIO()
            resized.save(buffer, format="JPEG", quality=95)
            return base64.b64encode(buffer.getvalue()).decode()
            
    def route_image(self, file_path: Union[str, Path]) -> Optional[str]:
        """ Process image """
        if os.path.getsize(file_path) > self.max_file_size:
            raise ValueError(f"File exceeds size limit of {self.max_file_size} bytes")
            
        image_type = self._get_image_type(file_path)
        if image_type is None:
            return None
            
        try:
            if image_type == "RAW":
                return self.process_raw_image(file_path)
                
            with Image.open(file_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                    
                if img.width <= 0 or img.height <= 0:
                    raise ValueError("Invalid image dimensions")
                    
                resized = self._resize_image(img)
                
                with io.BytesIO() as buffer:
                    resized.save(buffer, format="JPEG", quality=95)
                    return base64.b64encode(buffer.getvalue()).decode()
                    
        except (IOError, OSError) as e:
            raise ValueError(f"Image processing failed: {str(e)}")
            
        return None
        
    def process_image(self, image_path):    
        """ Process an image through the LLM
        """
        encoded = self.route_image(image_path)
        
        if not encoded:
            return None, Path(image_path)

        return encoded, Path(image_path)
