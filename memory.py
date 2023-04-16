import os
import openai
import textwrap
import tiktoken
import pinecone
import uuid

def create_ada_embedding(data):
    return openai.Embedding.create(
        input=[data],
        model="text-embedding-ada-002"
    )["data"][0]["embedding"]

class PineconeMemory():

    def __init__(self):
        self.summarizer_model = os.getenv("SUMMARIZER_MODEL")
        self.max_context_size = int(os.getenv("MAX_CONTEXT_SIZE"))
        self.summarizer_chunk_size = int(os.getenv("SUMMARIZER_CHUNK_SIZE"))

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
        vector = create_ada_embedding(data)

        id = uuid.uuid1()

        self.index.upsert([(str(id), vector, {"data": data})])

    def get_context(self, data, num=5):
        vector = create_ada_embedding(data)
        results = self.index.query(
            vector, top_k=num, include_metadata=True
        )
        sorted_results = sorted(results.matches, key=lambda x: x.score)
        results_list = [str(item["metadata"]["data"]) for item in sorted_results]
        context = "\n".join(results_list)

        num_tokens = len(tiktoken.encoding_for_model(self.summarizer_model).encode(context))

        # Summarize memory contents if they're too large to fit into the LLM context
        if (num_tokens > self.max_context_size):
            avg_chars_per_token = len(context) / num_tokens
            chunk_size = int(avg_chars_per_token * self.summarizer_chunk_size)
            chunks = textwrap.wrap(context, chunk_size)
            summary_size = int(self.max_context_size / len(chunks))
            context = ""

            for chunk in chunks:
                rs = openai.ChatCompletion.create(
                    model=self.summarizer_model,
                    messages = [
                        {"role": "user", "content": f"Shorten the following memory chunk of an autonomous agent from a first person perspective, {summary_size} tokens max."},
                        {"role": "user", "content": f"Do your best to retain all semantic information including tasks performed by the agent, website content, important data points and hyper-links:\n\n{chunk}"}, 
                    ])
                context += rs['choices'][0]['message']['content']

        return context
