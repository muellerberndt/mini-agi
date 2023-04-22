"""
Memory implementation for MicroGPT.
"""

# pylint: disable=line-too-long, import-error

import os
import uuid
import textwrap
from typing import List
from abc import abstractmethod
import openai
import tiktoken


def create_ada_embedding(data: str):
    """
    Create an embedding using the OpenAI API.

    :param data: Data to create embedding for

    """
    return openai.Embedding.create(
        input=[data],
        model="text-embedding-ada-002"
    )["data"][0]["embedding"]

class Memory:
    """
    Abstract base class for various memory implementations.
    """
    def __init__(self):
        self.summarizer_model = os.getenv("SUMMARIZER_MODEL")
        self.max_context_size = int(os.getenv("MAX_CONTEXT_SIZE"))
        self.summarizer_chunk_size = int(os.getenv("SUMMARIZER_CHUNK_SIZE"))

    def summarize_memory_if_large(self, memory: str, max_tokens: int, summarizer_hint = None) -> str:
        """
        Summarize a memory string if it exceeds the max_tokens limit.

        Args:
            memory (str): The memory string to be summarized.
            max_tokens (int): The maximum token limit.

        Returns:
            str: The summarized memory string.
        """
        num_tokens = len(tiktoken.encoding_for_model(
            self.summarizer_model).encode(memory))

        if num_tokens > max_tokens:
            avg_chars_per_token = len(memory) / num_tokens
            chunk_size = int(avg_chars_per_token * self.summarizer_chunk_size)
            chunks = textwrap.wrap(memory, chunk_size)
            summary_size = int(max_tokens / len(chunks))
            memory = ""

            print(f"Summarizing memory, {len(chunks)} chunks.")

            for chunk in chunks:

                messages=[
                    {"role": "user", "content": f"Shorten the following memory chunk of an autonomous agent from a first person perspective, {summary_size} tokens max."},
                    {"role": "user", "content": f"Do your best to retain all semantic information including tasks performed by the agent, website content, important data points and hyper-links:\n\n{chunk}"},
                ]

                if summarizer_hint is not None:
                    messages.append(
                        {"role": "user", "content": f"Pay particular attention to information related to this objective: {summarizer_hint}"},
                    )

                response = openai.ChatCompletion.create(
                    model=self.summarizer_model,
                    messages=messages,
                )

                memory += response['choices'][0]['message']['content']

        return memory

    @abstractmethod
    def add(self, data: str):
        """
        Add a data entry to the memory.

        Args:
            data (str): The data string to be added to the memory.
        """
        raise NotImplementedError

    @abstractmethod
    def get_context(self, data, num=5):
        """
        Retrieve context data from the memory based on a query.

        Args:
            data: The query data.
            num (int, optional): The number of memory items to retrieve. Defaults to 5.

        Returns:
            str: The retrieved context.
        """
        raise NotImplementedError


memory_type = os.getenv("MEMORY_TYPE")

if memory_type == "pinecone":
    import pinecone

    class PineconeMemory(Memory):
        """
        Pinecone memory implementation.
        """
        def __init__(self):
            super().__init__()
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

        def add(self, data: str):
            """
            Add a data entry to the Pinecone memory.

            Args:
                data (str): The data string to be added to the memory.
            """
            vector = create_ada_embedding(data)

            _id = uuid.uuid1()

            self.index.upsert([(str(_id), vector, {"data": data})])

        def get_context(self, data, num=5):
            """
            Retrieve context data from the Pinecone memory based on a query.

            Args:
                data: The query data.
                num (int, optional): The number of memory items to retrieve. Defaults to 5.

            Returns:
                str: The retrieved context.
            """
            vector = create_ada_embedding(data)
            results = self.index.query(
                vector, top_k=num, include_metadata=True
            )
            sorted_results = sorted(results.matches, key=lambda x: x.score)
            results_list = [str(item["metadata"]["data"])
                            for item in sorted_results]
            context = "\n".join(results_list)

            context = self.summarize_memory_if_large(
                context, self.max_context_size)

            return context

elif memory_type == "postgres":
    import psycopg2
    from sklearn.metrics.pairwise import cosine_similarity

    class PostgresMemory(Memory):
        """
        Postgres memory implementation.
        """
        def __init__(self):
            super().__init__()

            self.conn = psycopg2.connect(
                host=os.getenv("POSTGRES_HOST"),
                dbname=os.getenv("POSTGRES_DB"),
                user=os.getenv("POSTGRES_USER"),
                password=os.getenv("POSTGRES_PASSWORD")
            )

            self._create_table_if_not_exists()

            if os.getenv("CLEAR_DB_ON_START") in ['true', '1', 't', 'y', 'yes']:
                self._clear_table()

        def _create_table_if_not_exists(self):
            """
            Create a memory table in the Postgres database if it does not exist.
            """
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory (
                        id UUID PRIMARY KEY,
                        vector float[] NOT NULL,
                        data TEXT NOT NULL
                    );
                    """
                )
                self.conn.commit()

        def _clear_table(self):
            """
            Clear all entries in the memory table.
            """
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM memory;")
                self.conn.commit()

        def _get_vectors_from_memory(self) -> List:
            """
            Retrieve all memory vectors from the Postgres memory.

            Returns:
                List: A list of memory vectors.
            """
            with self.conn.cursor() as cur:
                cur.execute("SELECT id, vector, data FROM memory;")
                vectors = cur.fetchall()
            return vectors

        def add(self, data: str):
            """
            Add a data entry to the Postgres memory.

            Args:
                data (str): The data string to be added to the memory.
            """
            vector = create_ada_embedding(data)

            _id = uuid.uuid1()

            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO memory (id, vector, data) VALUES (%s, %s, %s);",
                    (str(_id), vector, data)
                )
                self.conn.commit()

        def get_context(self, data, num=5):
            """
            Retrieve context data from the Postgres memory based on a query.

            Args:
                data: The query data.
                num (int, optional): The number of memory items to retrieve. Defaults to 5.

            Returns:
                str: The retrieved context.
            """
            vector = create_ada_embedding(data)

            all_vectors = self._get_vectors_from_memory()
            all_vectors.sort(key=lambda x: cosine_similarity(
                [x[1]], [vector])[0][0], reverse=True)

            top_k_vectors = all_vectors[:num]
            results_list = [str(item[2]) for item in top_k_vectors]
            context = "\n".join(results_list)

            context = self.summarize_memory_if_large(
                context, self.max_context_size)

            return context

elif memory_type == "chromadb":
    import chromadb

    class ChromaDBMemory(Memory):
        """ 
        ChromaDB memory implementation.
        """

        def __init__(self):
            super().__init__()

            client = chromadb.Client()
            self.index = client.create_collection("microgpt")

            if os.getenv("CLEAR_DB_ON_START") in ['true', '1', 't', 'y', 'yes']:
                self.index.delete("microgpt")

            os.environ['TOKENIZERS_PARALLELISM'] = 'false'

        def add(self, data: str):
            """
            Add a data entry to the ChromaDB memory.

            Args:
                data (str): The data string to be added to the memory.
            """
            _id = uuid.uuid1()

            self.index.add(
                documents=[data],
                metadatas=[{"type": "memory"}],
                ids=[str(_id)]
            )

        def get_context(self, data: str, num: int=5):
            """
            Retrieve context data from the ChromaDB memory based on a query.

            Args:
                data (str): The query data.
                num (int, optional): The number of memory items to retrieve. Defaults to 5.

            Returns:
                str: The retrieved context.
            """
            index_count = self.index.count()
            if index_count == 0:
                return data
            if index_count < num:
                num = index_count
            results = self.index.query(
                query_texts=[data],
                n_results=num
            )

            results_list = results["documents"][0]
            context = "\n".join(results_list)
            context = self.summarize_memory_if_large(
                context, self.max_context_size)

            return context

else:
    raise ValueError("Invalid MEMORY_TYPE environment variable")


def get_memory_instance():
    """
    Return the memory implementation based on memory_type
    """
    if memory_type == "pinecone":
        return PineconeMemory()
    if memory_type == "postgres":
        return PostgresMemory()
    if memory_type == "chromadb":
        return ChromaDBMemory()

    raise ValueError("Invalid MEMORY_TYPE environment variable")
