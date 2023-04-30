# import Libraries
import re
import os
import pickle
from dataclasses import dataclass
from langchain.prompts import PromptTemplate


# Load the vector store
with open("vector_store.pkl", "rb") as f:
    docsearch = pickle.load(f)

FLAG = 'no'

# Clean the text
def clean_text(ans):
    temp = ans
    temp = temp.lower()
    temp = re.sub(r'[^\w\s]', '', temp)
    temp = temp.replace(" ", "")
    return temp

# Load the prompt
@dataclass
class templates:
    prompt_template = """Use the following pieces of context to answer the question at the end. If the answer is not from the context, just say "no", don't try to make up an answer.
                {context}
                Question: {question}
                Answer in English:"""
    

def get_prompt():
    PROMPT_1 = PromptTemplate(
        template=templates.prompt_template, input_variables=["context", "question"]
        )
    return PROMPT_1


def chunk_text(text, max_length):
    """
    Split a long text into chunks of a specified maximum length.

    :param text: The long text to be split.
    :param max_length: The maximum length of each chunk.
    :return: A list of text chunks.
    """
    chunks = []
    start = 0
    end = max_length
    while end < len(text):
        chunks.append(text[start:end])
        start = end
        end += max_length
    chunks.append(text[start:])
    return chunks

if __name__ == "__main__":
    print("This is a test file. Please run microgpt.py")