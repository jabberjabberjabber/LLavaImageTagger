**LLavaImageTagger aka LLMImageIndexer**

This script crawls a directory and looks for image files. When it finds one it does the following:

* Sends the image to the local KoboldCPP API and asks it for a caption
* Takes that caption and sends it back to the KoboldCPP API and asks it to use the caption to create a title, keyword tags, a summary, and a suggested filename
* Edits the image XMP metadata tags to include the title, tags, and summary (this overwrites any metadata in those fields already)
* Stores this information in a local TinyDB database

You can then do all sorts of things with it. Probably the most useful is to use Everything 1.5 to index the images and include the XMP metadata so that you can search and sort the images by tag, description, and title.

*Requirements*

* KoboldCPP
* a llava compatible LLM and projector
* the model has to at least somewhat understand how to respond with a JSON object
* python 3.10 and dependencies

*Dependencies*

* TinyDB for a plain-text readable JSON database to keep track of indexed files
* xxhash for fast file hashing
* exiftool-py to do the metadata stuff
* requests for API calls
* json-repair to fix mutilated JSON responses from brain-dead LLMs

*Suggested models*

For model I suggest ShareGPT4V-13B as the LLM and llava-v1.6-vicuna-13b-mmproj-model-f16 as the image projector.

If you don't have a lot of VRAM use llava-phi-3-mini as the LLM and llava-phi-3-mini-mmproj-f16 as the image projector.

*How to use*

* Start KoboldCPP gui
* Make sure context is set to 4096 
* Choose the LLM and projector
* Once it is running, type python llmii.py directory_to_crawl

It will take A LONG TIME. But because it keeps a database it won't lose its place if you kill it and start it again.

*Flags:*

```
--api-url

--no-crawls

--force-rehash
```

**How to Install**

Create a new conda or python environment if you want, then type:

```
pip install -r requirements.txt
```

*Troubleshooting*

Make sure you have exiftool installed on your path. Try putting command arguments in quotes. Make sure KoboldCPP is running. Make sure your model can output a JSON object in a somewhat not-stupid way.

**Links**

* https://huggingface.co/koboldcpp/mmproj
* https://huggingface.co/Lin-Chen/ShareGPT4V-13B
* https://huggingface.co/microsoft/Phi-3-mini-4k-instruct   
