# import Libraries 
import os
from tqdm import tqdm
import openai
openai.api_key = os.getenv("OPENAI_API_KEY")
from git import Repo
from langchain.document_loaders import GitLoader
from langchain.chat_models import ChatOpenAI
from langchain import  LLMChain
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from pathlib import Path
from utils import chunk_text
from dotenv import load_dotenv
load_dotenv()


class Generate_data:
  """
  Summarize the data from the database
  """
  def __init__(self):
    self.chat = ChatOpenAI(temperature=0)
    template="You are a helpful assistant that takes {text} as input and explains code present in the {text}"
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    example_human = SystemMessagePromptTemplate.from_template("Hi", additional_kwargs={"name": "example_user"})
    example_ai = SystemMessagePromptTemplate.from_template("Argh me mateys", additional_kwargs={"name": "example_assistant"})
    human_template="{text}"
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_template)
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, example_human, example_ai, human_message_prompt])
    self.chain = LLMChain(llm=self.chat, prompt=chat_prompt)

  def run_chain(self, text):
    try:
        ans = self.chain.run(text)
        return ans
    except Exception as e:
        raise e
  

if __name__ == "__main__":

    chain = Generate_data()
    clone_repo = os.getenv("CLONE_REPO")
    clone_repo_path = os.getenv("CLONE_REPO_PATH")

    if clone_repo_path is None or not clone_repo_path:
        clone_repo_path = os.path.join(Path.home(), "data")
        if not os.path.exists(clone_repo_path):
            os.makedirs(clone_repo_path)

    repo = Repo.clone_from(
    clone_repo, to_path=clone_repo_path
    )
    branch = repo.head.reference
    loader = GitLoader(repo_path=clone_repo_path, file_filter=lambda file_path: file_path.endswith(os.getenv("FILES_TO_EXTRACT")))
    data = loader.load()

    all_text = []
    for i, var in enumerate(data):
        chunks = chunk_text(var.page_content, 1500)
        all_text.extend(chunks)
    complete_text = ""
    for i in tqdm(all_text, total = len(all_text)):
        ans = chain.run_chain(i)
        complete_text += ans

    SaveFile = os.getenv("PATH_TO_STORE_OUTPUT")
    if SaveFile is None or not SaveFile:
        SaveFile = os.path.join(Path.home(), "data.txt")
        if not os.path.exists(SaveFile):
            os.makedirs(SaveFile)

    file = open(SaveFile, "w")
    file.write(complete_text)
    file.close()



