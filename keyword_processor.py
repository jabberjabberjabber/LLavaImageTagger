import inflect
from nltk.corpus import wordnet
from collections import Counter
from typing import List, Set, Dict
import os
import exiftool

class KeywordProcessor:
    def __init__(self):
        self.p = inflect.engine()
        self.after_keywords = 0
        self.before_keywords = 0
        self.after_keyword_list = list(set([]))
        
    def handle_plurals(self, word: str) -> str:
        singular = self.p.singular_noun(word)
        return singular if singular else word

    def get_synonyms(self, word: str) -> Set[str]:
        synonyms = set()
        for syn in wordnet.synsets(word):
            for lemma in syn.lemmas():
                synonyms.add(lemma.name().lower().replace('_', ' '))
        return synonyms

    def process_keywords(self, all_keywords: List[str], mode: str):
        singular_keywords = [self.handle_plurals(str(keyword).lower()) for keyword in all_keywords]
        keyword_freq = Counter(singular_keywords)
        
        synonym_groups = {}
        for keyword in keyword_freq:
            if keyword not in synonym_groups:
                synonyms = self.get_synonyms(keyword)
                group = [keyword] + [syn for syn in synonyms if syn in keyword_freq]
                main_keyword = max(group, key=lambda x: keyword_freq[x])
                for syn in group:
                    synonym_groups[syn] = main_keyword
        
        return keyword_freq, synonym_groups

    def update_keywords(self, keywords: Set[str], synonym_groups: Dict[str, str], mode: str) -> Set[str]:
        new_keywords = set()
        for keyword in keywords:
            singular = self.handle_plurals(str(keyword).lower())
            if mode == "expand":
                new_keywords.update(self.get_synonyms(singular))
                new_keywords.add(singular)
            elif mode == "dedupe":
                if singular in synonym_groups:
                    new_keywords.add(synonym_groups[singular])
                else:
                    new_keywords.add(singular)
            else:  # "keep"
                new_keywords.add(singular)
        return new_keywords

    def process_directory(self, directory, mode, no_crawl):
        file_keywords = {}
        all_keywords = []
        file_paths = []
        if no_crawl:
            for file in os.listdir(directory):
                file_paths.append(os.path.join(directory, file))
        else:
            for root, _, files in os.walk(directory):
                for file in files:
                    file_paths.append(os.path.join(root, file))
        
        with exiftool.ExifToolHelper() as et:
            for file_path in file_paths:
                try:
                    metadata = et.get_metadata(file_path)[0]
                    keywords = set()
                    for field in ["XMP:Subject", "IPTC:Keywords", "MWG:Keywords", "Keywords", "Composite:Keywords", "Subject"]:
                        if field in metadata:
                            value = metadata[field]
                            if isinstance(value, list):
                                keywords.update(value)
                            else:
                                keywords.add(value)
                    all_keywords.extend(keywords)
                    file_keywords[file_path] = keywords
                except Exception as e:
                    #print(f"Error processing {file_path}: {str(e)}")
                    pass
        self.before_keywords += len(all_keywords)
        keyword_freq, synonym_groups = self.process_keywords(all_keywords, mode)
        
        updated_file_keywords = {}
        for file_path, keywords in file_keywords.items():
            updated_keywords = self.update_keywords(keywords, synonym_groups, mode)
            if updated_keywords != keywords:
                updated_file_keywords[file_path] = updated_keywords
        return updated_file_keywords

    def update_metadata(self, file_keywords, no_backup):        
        with exiftool.ExifToolHelper() as et:
            for file_path, keywords in file_keywords.items():
                keyword_list = list(set(keywords))
                self.after_keyword_list += keyword_list
                metadata = {
                    #"XMP:Subject": [],
                    #"IPTC:Keywords": [],
                    "MWG:Keywords": keyword_list,
                    #"Keywords": []
                }
                try:
                    if no_backup:
                        et.set_tags(
                            file_path,
                            tags=metadata,
                            params=["-P", "-overwrite_original"],
                        )
                    else:
                        et.set_tags(
                            file_path,
                            tags=metadata,
                        )
                except Exception as e:
                    print(f"Error updating metadata for {file_path}: {str(e)}")
        return self.before_keywords, len(self.after_keyword_list)
        