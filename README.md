# LLMImageIndexer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

LLMImageIndexer creates keywords and captions for images and puts them into the file's metadata using a local AI. No data leaves your computer during this process -- once the install and download of the model weights and KoboldCpp executable is completed the internet is not needed or used. 

By storing the information in the file metadata the images can be moved, renamed, or copied without issue. The indexer can also be run multiple times on the same files and will not reprocess them unless directed to.

Uses the Qwen2-VL 2B model, a 2 billion parameter multimodal local large language model. It runs on your machine to recognize images and describe them and generate keywords. However, you can use any image model you like as long as it has weights in the "gguf" filetype and it has an appropriate "mmproj" image projector. 

## Features
 
- **Image Analysis**: Utilizes a local AI model to generate a list of keywords and a caption for each image
- **Metadata Enhancement**: Can automatically edit image metadata with generated tags
- **Local Processing**: All processing is done locally on your machine
- **Multi-Format Support**: Handles a wide range of image formats, including all major raw camera files
- **User-Friendly GUI**: Includes a GUI and installer. Relies on Koboldcpp, a single executable, for all AI functionality
- **GPU Acceleration**: Will use Apple Metal, Nvidia CUDA, or AMD (Vulkan) hardware if available to greatly speed inference
- **Cross-Platform**: Supports Windows, macOS ARM, and Linux
- **Stop and Start Capability**: Can stop and start without having to reprocess all the files again
- **One or Two Step Processing**: Can do keywords and a simple caption in one step, or keywords and a detailed caption in two steps

## Important Information

It is recommended to have a discrete graphics processor in your machine. Running this on CPU will be extremely slow.

This tool verifies keywords and de-pluralizes them using rules that apply to English. Using it to generate keywords in other languages may have strange results.

This tool operates directly on image file metadata. It will write to one or more of the following fields:

  1. Subject
  2. Any keyword field
  3. Description
  4. Identifier
  5. Status
  
The "Status" and "Identifier" fields are used to track the processing state of images. The "Description" field is used for the image caption, and "Subject" or "Keyword" fields are used to hold keywords.

**The use of the Identifier tag means you can manage your files and add new files, and run the tool as many times as you like without worrying about reprocessing the files that were previously keyworded by the tool.**
     
## Installation

### Prerequisites

- Python 3.8 or higher
- KoboldCPP

**A vision model is needed, but if you use the llmii-run.bat to open it, then the first time it is run it will download the Qwen2-VL 2B Q4_K_M gguf and F16 projector from Bartowski's repo on huggingface. If you don't want to use that, just open llmii-no-kobold.bat instead and open Koboldcpp.exe and load whatever model you like.**
  
### Windows Installation

1. Clone the repository or download the [ZIP file](https://github.com/jabberjabberjabber/LLavaImageTagger/archive/refs/heads/main.zip) and extract it

2. Install [Python for Windows](https://www.python.org/downloads/windows/)

3. Run `llmii-run.bat` and wait exiftool to install and KoboldCpp to download. When it is complete you must start the file again. If you called it from a terminal window you will need to close the windows and reopen it. It will then create a python environment and download the model weights

### macOS Installation (including ARM)

1. Clone the repository or download the [ZIP file](https://github.com/jabberjabberjabber/LLavaImageTagger/archive/refs/heads/main.zip) and extract it

2. Install Python 3.7 or higher if not already installed. You can use Homebrew:
   ```
   brew install python
   ```

3. Install ExifTool:
   ```
   brew install exiftool
   ```

4. Run the script:
   ```
   ./llmii-run.sh
   ```
   
5. If KoboldCpp fails to run, open a terminal in the LLMImageIndexer folder:
   ```
   xattr -cr koboldcpp-mac-arm64
   chmod +x koboldcpp-mac-arm64
   ```

### Linux Installation

1. Clone the repository or download and extract the ZIP file

2. Install Python 3.7 or higher if not already installed. Use your distribution's package manager, for example on Ubuntu:
   ```
   sudo apt-get update
   sudo apt-get install python3 python3-pip
   ```

3. Install ExifTool. On Ubuntu:
   ```
   sudo apt-get install libimage-exiftool-perl
   ```

4. Run the script:
   ```
   ./llmii-run.sh
   ```

5. If KoboldCpp fails to run, open a terminal in the LLMImageIndexer folder:
   ```
   chmod +x koboldcpp-linux-x64
   ```

For all platforms, the script will set up the Python environment, install dependencies, and download necessary model weights. This initial setup is performed only once and will take a few minutes depending on your download speed.

## Usage

1. Launch the LLMImageIndexer GUI:
   - On Windows: Run `llmii-run.bat`
   - On macOS/Linux: Run `./llmii-run.sh`

2. Ensure KoboldCPP is running. Wait until you see the following message in the KoboldCPP window:
   ```
   Please connect to custom endpoint at http://localhost:5001
   ```

3. Configure the indexing settings in the GUI

4. Click "Run Image Indexer" to start the process

5. Monitor the progress in the output area of the GUI.

## Configuration Options

- **Directory**: Target image directory (includes subdirectories by default)
- **API URL**: KoboldCPP API endpoint (change if running on another machine)
- **API Password**: Set if required by your KoboldCPP setup
- **Caption Instruction**: The instruction to use when generating a detailed caption
- **Write a detailed caption**: Have the LLM describe the image in detail and set it in XMP:Description (at least doubles processing time). This will overwrite any existing caption in the image metadata
- **GenTokens**: Amount of tokens for the LLM to use per generation
- **Don't crawl subdirectories**: Disable scanning of subdirectories
- **Reprocess all files again**: Will generate keywords and captions for all images files regardless of prior processing (checking this will include failed and orphan files in reprocessing)
- **Reprocess failed files**: If a file was marked failed during prior processing, it will processed again. If this is unchecked, previously failed files are ignored
- **Reprocess orphan files**: If the file was previously processed, and the llmii.json file in the root directory was deleted, or the image file was moved or renamed, if will be processed again. If this box is unchecked, previously processed files will be ignored, regardless of its existence in the database
- **Don't make backups**: Before changing anything in a file, a backup will be made called "Filename.extension_original". If this box is checked, these files will not be created and the original file will be altered with no backup
- **Pretend mode**: Simulate processing without writing to files or database
- **Clear existing keywords and captions and write new ones**: If this is selected any keywords and captions that exist will be overwritten
- **Add to existing keywords**: If this is selected then any keywords that exist will be appended to the new keywords, and any captions created during this process will be discarded. This is useful for running on image files already processed (with the reprocess all files box checked) to add more keywords to them

## More Information and Troubleshooting

Consult [the wiki](https://github.com/jabberjabberjabber/LLavaImageTagger/wiki) for more information and troubleshooting steps.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

- [ExifTool](https://exiftool.org/) for metadata manipulation
- [KoboldCPP](https://github.com/LostRuins/koboldcpp) for local AI processing
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) for the GUI framework
- [Fix Busted JSON](https://github.com/Qarj/fix-busted-json) and [Json Repair](https://github.com/josdejong/jsonrepair) for help with mangled JSON parsing
