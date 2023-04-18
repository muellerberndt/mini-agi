import os
import openai
import textwrap
import tiktoken
import uuid
import redis
import pinecone

def create_ada_embedding(data):
    return openai.Embedding.create(
        input=[data],
        model="text-embedding-ada-002"
    )["data"][0]["embedding"]

class Memory:

    def __init__(self):
        self.backend = os.getenv("MEMORY_BACKEND")

        self.summarizer_model = os.getenv("SUMMARIZER_MODEL")
        self.max_context_size = int(os.getenv("MAX_CONTEXT_SIZE"))
        self.summarizer_chunk_size = int(os.getenv("SUMMARIZER_CHUNK_SIZE"))

        if self.backend == "pinecone":
            pinecone.init(
                api_key=os.getenv("PINECONE_API_KEY"),
                environment=os.getenv("PINECONE_REGION")
            )

            if "microgpt" not in pinecone.list_indexes():
                print("Creating Pinecone index...")
                pinecone.create_index(
                    "microgpt", dimension=1536, metric="cosine", pod_type="p1"
                )

            self.index = pinecone.Index("microgpt")

            if os.getenv("CLEAR_DB_ON_START") in ['true', '1', 't', 'y', 'yes']:
                self.index.delete(deleteAll='true')

        elif self.backend == "redis":
            self.redis_client = redis.Redis(
                host=os.getenv("REDIS_HOST"),
                port=int(os.getenv("REDIS_PORT")),
                db=int(os.getenv("REDIS_DB")),
                password=os.getenv("REDIS_PASSWORD")
            )

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
        if self.backend == "pinecone":
            vector = create_ada_embedding(data)

            id = uuid.uuid1()

            self.index.upsert([(str(id), vector, {"data": data})])

        elif self.backend == "redis":
            id = str(uuid.uuid1())

            self.redis_client.set(id, data)

    def get_context(self, data, num=5):
        if self.backend == "pinecone":
            vector = create_ada_embedding(data)
            results = self.index.query(
                vector, top_k=num, include_metadata=True
            )
            sorted_results = sorted(results.matches, key=lambda x: x.score)
            results_list = [str(item["metadata"]["data"]) for item in sorted_results]
            context = "\n".join(results_list)

        if self.backend == "pinecone":
            vector = create_ada_embedding(data)
            results = self.index.query(
                vector, top_k=num, include_metadata=True
            )
            sorted_results = sorted(results.matches, key=lambda x: x.score)
            results_list = [str(item["metadata"]["data"]) for item in sorted_results]
            context = "\n".join(results_list)

            context = self.summarize_memory_if_large(context, self.max_context_size)

        elif self.backend == "redis":
            keys = self.redis_client.keys()

            if len(keys) > 0:
                data_list = self.redis_client.mget(keys)
                context = "\n".join([str(d, 'utf-8') for d in data_list])
            else:
                context = ""

        return context

           
