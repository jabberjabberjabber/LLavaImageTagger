# LLMImageIndexer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

LLMImageIndexer is an intelligent image processing and indexing tool that leverages local AI to generate comprehensive metadata for your image collection. No data is sent to or from your computer to do this except for during the initial process of downloading dependencies and model weights.

![LLMImageIndexer Screenshot](screenshot.png)

## Features

- Automatically crawls directories for image files
- Generates AI-powered captions, titles, tags, and summaries for each image
- Edits image metadata with the generated information
- Stores processed data in a local TinyDB database for easy querying
- Compatible with xnimage-mp for advanced browsing and searching capabilities

## Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Contributing](#contributing)
- [License](#license)

## Installation

### Windows

1. Clone the repository or download the [ZIP file](https://github.com/jabberjabberjabber/LLavaImageTagger/archive/refs/heads/main.zip) and extract it.

2. Install [Python for Windows](https://www.python.org/downloads/windows/).

3. Install ExifTool:
   - Option 1: Use the [installer](https://oliverbetz.de/cms/files/Artikel/ExifTool-for-Windows/ExifTool_install_12.89_64.exe)
   - Option 2: Download the [executable](https://exiftool.org/install.html#Windows) and place it in the script folder

4. Download [KoboldCPP.exe](https://github.com/LostRuins/koboldcpp/releases) and place it in the script folder.

5. Run `llmii-run.bat`

The script will set up the Python environment, install dependencies, and download necessary model weights (6GB total). This initial setup is performed only once.

## Usage

1. Ensure KoboldCPP is running. You should see:
   ```
   Please connect to custom endpoint at http://localhost:5001
   ```

2. Configure the settings as needed (see [Configuration](#configuration) section).

3. Run the indexer to process your images.

## Configuration

- **Directory**: Target image directory (includes subdirectories by default)
- **API URL**: KoboldCPP API endpoint (change if running on another machine)
- **Password**: Set if required by your setup
- **No Crawl**: Disable subdirectory scanning
- **Force Rehash**: Reindex all files, including previously processed ones
- **Overwrite**: Skip creating backup files (default: creates 'image_name.jpg_original')
- **Dry Run**: Simulate processing without writing to files
- **Keywords**: Select metadata fields to write to images
- **Output**: View script progress and logs

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
