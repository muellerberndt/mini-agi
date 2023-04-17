import os
import openai
import textwrap
import tiktoken
import redis
import uuid

def create_ada_embedding(data):
    return openai.Embedding.create(
    input=[data],
    model="text-embedding-ada-002"
    )["data"][0]["embedding"]

    class RedisMemory():
        def __init__(self):
            self.summarizer_model = os.getenv("SUMMARIZER_MODEL")
            self.max_context_size = int(os.getenv("MAX_CONTEXT_SIZE"))
            self.summarizer_chunk_size = int(os.getenv("SUMMARIZER_CHUNK_SIZE"))

            self.redis_client = redis.Redis(
                host=os.getenv("REDIS_HOST"),
                port=os.getenv("REDIS_PORT"),
                db=os.getenv("REDIS_DB"),
                password=os.getenv("REDIS_PASSWORD")
            )

            if os.getenv("CLEAR_DB_ON_START") in ['true', '1', 't', 'y', 'yes']:
                self.redis_client.flushdb()

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

            id = uuid.uuid1()

            self.redis_client.hset("memory", str(id), data)

        def get_context(self, data, num=5):
            vector = create_ada_embedding(data)
            results = []

            for key, value in self.redis_client.hscan_iter("memory"):
                results.append((key, value))

            # Sort results based on cosine similarity
            results.sort(key=lambda x: cosine_similarity([vector], [create_ada_embedding(x[1])])[0][0], reverse=True)

            sorted_results = results[:num]
            results_list = [str(item[1]) for item in sorted_results]
            context = "\n".join(results_list)

            context = self.summarize_memory_if_large(context, self.max_context_size)

            return context
