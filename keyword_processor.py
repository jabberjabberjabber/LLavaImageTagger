from make_singular import de_pluralize
from nltk.corpus import wordnet
from collections import Counter
from typing import List, Set, Dict
import os
import exiftool

""" This whole thing is a total mess,
    but I am afraid if I touch it again it will break 
"""

class KeywordProcessor:
    def __init__(self, image_extensions, get_file_type_func):
        self.after_keywords = set()
        self.before_keywords = set()
        self.after_keyword_list = set()
        self.image_extensions = image_extensions
        self.get_file_type = get_file_type_func
        
    def handle_plurals(self, word: str) -> str:
        singular_keyword = de_pluralize(word)
        return singular_keyword

    def get_synonyms(word: str) -> Set[str]:
        synonyms = set()
        for syn in wordnet.synsets(word)[0]:
            for hyponym in syn.hypernyms()[0].hyponyms():
                synonyms.add(hyponym.name().lower().replace('_', ' '))
        return synonyms
    
    def are_synonyms(self, word1: str, word2: str) -> bool:
        synsets1 = wordnet.synsets(word1)
        synsets2 = wordnet.synsets(word2)
        
        for syn1 in synsets1:
            for syn2 in synsets2:
                if syn1 == syn2 or syn1.wup_similarity(syn2) > 0.8:
                    return True
        return False
    def process_synonyms(all_keywords: List[str]):
        singular_keywords = [handle_plurals(keyword.lower()) for keyword in all_keywords]
        keyword_freq = Counter(singular_keywords)
        
        synonym_groups = {}
        for keyword in keyword_freq:
            if keyword not in synonym_groups:
                synonyms = get_synonyms(keyword)
                group = [keyword] + [syn for syn in synonyms if syn in keyword_freq]
                main_keyword = max(group, key=lambda x: keyword_freq[x])
                for syn in group:
                    synonym_groups[syn] = main_keyword
        
        return keyword_freq, synonym_groups
    
    def process_keywords(self, all_keywords: List[str], mode: str):
        singular_keywords = [self.handle_plurals(str(keyword).lower()) for keyword in all_keywords]

        keyword_freq = Counter(singular_keywords)
        
        synonym_groups = {}
        processed_keywords = set()
        
        for keyword in keyword_freq:
            if keyword not in processed_keywords:
                group = [keyword]
                for other_keyword in keyword_freq:
                    if other_keyword != keyword and other_keyword not in processed_keywords:
                        if self.are_synonyms(keyword, other_keyword):
                            group.append(other_keyword)
                
                main_keyword = max(group, key=lambda x: keyword_freq[x])
                for syn in group:
                    synonym_groups[syn] = main_keyword
                    processed_keywords.add(syn)
        
        return keyword_freq, synonym_groups

    def update_keywords(self, keywords: Set[str], synonym_groups: Dict[str, str], mode: str) -> Set[str]:
        new_keywords = set()
        for keyword in keywords:
            try:
                singular = self.handle_plurals(str(keyword).lower())
                if mode == "expand":
                    new_keywords.add(singular)
                elif mode == "dedupe":
                    if singular in synonym_groups:
                        new_keywords.add(synonym_groups[singular])
                    else:
                        new_keywords.add(singular)
                else:
                    new_keywords.add(singular)
            except:
                pass
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
                file_extension = os.path.splitext(file_path)[1].lower()
                if self.get_file_type(file_extension):
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
                        print(f"Error processing {file_path}: {str(e)}")

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
                self.after_keyword_list.update(keyword_list)
                metadata = {
                    "MWG:Keywords": keyword_list,
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
        return list(self.after_keyword_list)

        