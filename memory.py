import os
import openai
import textwrap
import tiktoken
import pinecone
import uuid
from abc import ABC, abstractmethod
from typing import List


def create_ada_embedding(data):
    return openai.Embedding.create(
        input=[data],
        model="text-embedding-ada-002"
    )["data"][0]["embedding"]


class Memory():

    @abstractmethod
    def db_query(self, vector: List, top_k: int) -> List:
        pass

    @abstractmethod
    def db_insert(self, vector: List, data: str):
        pass

    def __init__(self):
        self.summarizer_model = os.getenv("SUMMARIZER_MODEL")
        self.max_context_size = int(os.getenv("MAX_CONTEXT_SIZE"))
        self.summarizer_chunk_size = int(os.getenv("SUMMARIZER_CHUNK_SIZE"))

    def summarize_memory_if_large(self, memory:str, max_tokens:int) -> str:
        num_tokens = len(tiktoken.encoding_for_model(self.summarizer_model).encode(memory))

        if num_tokens > max_tokens:
            avg_chars_per_token = len(memory) / num_tokens
            chunk_size = int(avg_chars_per_token * self.summarizer_chunk_size)
            chunks = textwrap.wrap(memory, chunk_size)
            summary_size = int(max_tokens / len(chunks))
            memory = ""

            print("Summarizing memory, {} chunks.".format(len(chunks)))

            for chunk in chunks:
                rs = openai.ChatCompletion.create(
                    model=self.summarizer_model,
                    messages = [
                        {"role": "user", "content": f"Shorten the following memory chunk of an autonomous agent from a first person perspective, {summary_size} tokens max."},
                        {"role": "user", "content": f"Do your best to retain all semantic information including tasks performed by the agent, website content, important data points and hyper-links:\n\n{chunk}"}, 
                    ])
                memory += rs['choices'][0]['message']['content']
        
        return memory
        

    def add(self, data: str):
        vector = create_ada_embedding(data)

        self.db_insert(vector, data)

    def get_context(self, data, num=5):
        vector = create_ada_embedding(data)

        results = self.db_query(vector, num)
        context = "\n".join(results)

        context = self.summarize_memory_if_large(context, self.max_context_size)

        return context


class PineconeMemory(Memory):
    def __init__(self):
        super(PineconeMemory, self).__init__()
         
        pinecone.init(
            api_key=os.getenv("PINECONE_API_KEY"),
            environment=os.getenv("PINECONE_REGION")
        )

        if "microgpt" not in pinecone.list_indexes():
            print("Creating Pinecode index...")
            pinecone.create_index(
                "microgpt", dimension=1536, metric="cosine", pod_type="p1"
            )

        self.index = pinecone.Index("microgpt")

        if os.getenv("CLEAR_DB_ON_START") in ['true', '1', 't', 'y', 'yes']:
            self.index.delete(deleteAll='true')

    def db_query(self, vector: List, top_k: int) -> List:
        results = self.index.query(
            vector, top_k=top_k, include_metadata=True
        )
        sorted_results = sorted(results.matches, key=lambda x: x.score)
        return [str(item["metadata"]["data"]) for item in sorted_results]

    def db_insert(self, vector: List, data: str):
        id = uuid.uuid1()

        self.index.upsert([(str(id), vector, {"data": data})])
        pass