### import Libraries
import os
import openai
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter
from langchain.document_loaders import TextLoader
from langchain.vectorstores import FAISS
from dotenv import load_dotenv
openai.api_key = os.getenv("OPENAI_API_KEY")
import pickle

load_dotenv()


if __name__ == "__main__":
    loader = TextLoader(os.getenv("DATABASE_TXT"))
    documents = loader.load()
    text_splitter = CharacterTextSplitter(chunk_size=1200, chunk_overlap=0)
    texts = text_splitter.split_documents(documents)

    embeddings = OpenAIEmbeddings()
    docsearch = FAISS.from_documents(texts, embeddings)
    with open("vector_store.pkl", 'wb') as f:
        pickle.dump(docsearch, f)