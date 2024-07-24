**LLMImageIndexer**

This script crawls a directory and looks for image files. When it finds one it does the following:

* Sends the image to the local KoboldCPP API and asks it for a caption
* Takes that caption and sends it back to the KoboldCPP API and asks it to use the caption to create a title, keyword tags, a summary, and a suggested filename
* Edits the image metadata tags to include the title, tags, and summary
* Stores this information in a local TinyDB database

You can then do all sorts of things with it. Probably the most useful is to use Windows Search or Everything 1.5 to search the images and sort the images by tag, description, and title.



*Requirements*

* KoboldCPP
* a llava compatible LLM and projector
* the model has to at least somewhat understand how to respond with a JSON object
* python 3.10 and dependencies

*Dependencies*

* TinyDB for a plain-text readable JSON database to keep track of indexed files
* xxhash for fast file hashing
* pyexiftool to do the metadata stuff
* requests for API calls
* json-repair to fix mutilated JSON responses from brain-dead LLMs

*Suggested models*

For model use ShareGPT4V-7B or ShareGPT4V-13B with llava-v1.6-vicuna-7b-mmproj-model-f16 or llava-v1.6-vicuna-13b-mmproj-model-f16 as projectors. Don't use flash attention or quantkv

*How to use*

* Start KoboldCPP gui
* Make sure context is set to 4096 
* Choose the LLM and projector
* Once it is running, type python llmii.py directory_to_crawl

It will take A LONG TIME. But because it keeps a database it won't lose its place if you kill it and start it again.

*Flags:*

```
--api-url
```
Place the api-url here, no trailing slash. Defaults to http://localhost:5001
```
--no-crawl
```
Don't go through directories recursively.
```
--force-rehash
```
Index all files again, whether they have been indexed before or not.
```
--dry-run
```
Don't write any files. Pretend and see what you would get.
```
--overwrite
```
Copy over file metadata without creating a backup _original file.

**How to Install**

Create a new conda or python environment if you want, then type:

```
pip install -r requirements.txt
```

*Troubleshooting*

Don't end directory with a slash. Don't end api-url with a slash. Make sure you have exiftool installed on your path. Try putting command arguments in quotes. Make sure KoboldCPP is running. Make sure your model can output a JSON object in a somewhat not-stupid way.

**FAQ**

Q: What tags does it write to?

A: Keywords, Description, Title

Q: What is an 'image'?

A: Any file that ends with jpeg, jpg, png, gif, webp, tiff, psd.

Q: What are the prompts? Can I change the prompts? It is using the wrong prompt!

A: Open the file. It is text. Change it yourself. Save it. Run it. Congrats, you are a coder.

**Notes**

This is not a 'just works' project. It requires that you kinda know what you are doing. I made it for myself, and am happy to share it, but I kind of suck at doing things like handling edge cases or errors or writing documentation. Run this on a directory of test files before you do anything serious with it, and know that LLMs can output all sorts of weird stuff, so it does anything you don't like, then you have been warned. 
