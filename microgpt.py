"""
MicroGPT main executable.
This script serves as the main entry point for the MicroGPT application. It provides a command-line
interface for users to interact with a GPT-3.5/4 language model, leveraging memory management and
context-based reasoning to achieve user-defined objectives. The agent can issue various types of
commands, such as executing Python code, running shell commands, reading files, searching the web,
scraping websites, and conversing with users.
"""

# pylint: disable=invalid-name, broad-exception-caught, exec-used, unspecified-encoding, wrong-import-position, import-error

import os
import sys
import subprocess
import platform
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from urllib.request import urlopen
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain import OpenAI
from termcolor import colored
import openai
from duckduckgo_search import ddg
from spinner import Spinner
from thinkgpt.llm import ThinkGPT
from thinkgpt.gpt_select import SelectChain

operating_system = platform.platform()

def get_agent(model="gpt-4"):
    select_llm = OpenAI(model_name="gpt-3.5-turbo", verbose=False)
    select_chain = SelectChain.from_llm(llm=select_llm, select_examples=SELECT_TOOL_EXAMPLES, verbose=False)
    agent = ThinkGPT(model_name=model, select_chain=select_chain, verbose=False)
    return agent

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
DEBUG = os.getenv("DEBUG") in ['true', '1', 't', 'y', 'yes']

tools = ['execute_python', 'execute_shell', 'read_file', 'web_search', 'web_scrape', 'talk_to_user',  'done']
question = "Which command would you use for to achieve the following task ? Task: {task}. Choose 'done' command *if* " \
           "the objective was achieved."


SELECT_TOOL_EXAMPLES = [
    {
        "question": question.format(task=task),
        "options_text": '\n'.join(tools),
        "answer": answer
    }
    for task, answer in [
        ("Search for websites relevant to salami pizza.", "web_search"),
        ("Scrape information about Apples.", 'web_scrape'),
        ("I need to ask the user for guidance.", 'talk_to_user'),
        (">Write 'Hello, world!' to file", 'execute_python')
    ]
]
SYSTEM_PROMPT = f"You are an autonomous agent running on {operating_system}." + "You want to achieve the following objective: {objective}\n"

NEXT_THOUGHT_PROMPT = SYSTEM_PROMPT + """
Carefully consider your next THOUGHT.
This is the previous memory:
{context}
Say I'm done if the objective was achieved based.
"""

NEXT_ARG_PROMPT = SYSTEM_PROMPT + """
What is the argument that you would pick for the following thought and command ?

Your response may have multiple lines if the command is execute_python.
if the command is execute_shell, use only non-interactive shell commands.
Python code run with execute_python must end with an output "print" statement.
DO NOT CHAIN MULTIPLE COMMANDS.
DO NOT INCLUDE EXTRA TEXT BEFORE OR AFTER THE COMMAND.
This is the previous context: {context}


Examples:

THOUGHT: Search for websites relevant to salami pizza.
COMMAND: web_search
RESPONSE: 
salami pizza

THOUGHT: Scrape information about Apples.
COMMAND: web_scrape
RESPONSE: 
https://en.wikipedia.org/wiki/Apple

THOUGHT: I need to ask the user for guidance.
COMMAND: talk_to_user
RESPONSE: 
What is URL of Domino's Pizza API?

THOUGHT: Write 'Hello, world!' to file
COMMAND: execute_python
RESPONSE:
with open('hello_world.txt', 'w') as f:
    f.write('Hello, world!')
    
Your reply now:
THOUGHT: {thought}
COMMAND: {command}
RESPONSE:
"""

if __name__ == "__main__":

    model = os.getenv("MODEL")
    agent = get_agent(model)

    if len(sys.argv) != 2:
        print("Usage: microgpt.py <objective>")
        sys.exit(0)

    objective = sys.argv[1]
    max_memory_item_size = int(os.getenv("MAX_MEMORY_ITEM_SIZE"))
    context = objective
    thought = "You awakened moments ago."

    work_dir = os.getenv("WORK_DIR")

    if work_dir is None or not work_dir:
        work_dir = os.path.join(Path.home(), "microgpt")
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)

    print(f"Working directory is {work_dir}")

    try:
        os.chdir(work_dir)
    except FileNotFoundError:
        print("Directory doesn't exist. Set WORK_DIR to an existing directory or leave it blank.")
        sys.exit(0)

    while True:
        context = agent.remember(f"{objective}, {thought}", limit=5, sort_by_order=True)
        context = "\n".join(context)
        context = agent.chunked_summarize(context, max_tokens=int(os.getenv("MAX_CONTEXT_SIZE")))

        if DEBUG:
            print(f"CONTEXT:\n{context}")

        with Spinner():

            try:
                thought = agent.predict(prompt=NEXT_THOUGHT_PROMPT.format(operating_system=operating_system, context=context, objective=objective))
                command = agent.select(question.format(task=thought), options=tools)

            except openai.error.InvalidRequestError as e:
                if 'gpt-4' in str(e):
                    print("Prompting the gpt-4 model failed. Falling back to gpt-3.5-turbo")
                    agent = get_agent(model='gpt-3.5-turbo')

                    continue
                print("Error accessing the OpenAI API: " + str(e))
                sys.exit(0)


        try:
            if command == "done":
                print("Objective achieved.")
                sys.exit(0)
            elif command is None:
                continue
            else:
                argument = agent.predict(prompt=NEXT_ARG_PROMPT.format(objective=objective, context=context, thought=thought, command=command))
                if DEBUG:
                    print(f"Thought:\n{thought}\nCommand:\n{command}\nArg:\n{argument}")


            # Remove unwanted code formatting backticks
            argument = argument.replace("```", "")

            mem = f"Your thought: {thought}\nYour command: {command}"\
                f"\nCmd argument:\n{argument}\nResult:\n"

        except Exception as e:
            print(colored("Unable to parse response. Retrying...\n", "red"))
            continue

        if command == "talk_to_user":
            print(colored(f"MicroGPT: {argument}", 'cyan'))
            user_input = input('Your response: ')
            agent.memorize(f"{mem}The user responded with: {user_input}.")
            continue

        _argument = argument.replace("\n", "\\n") if len(argument) < 64 else f"{argument[:64]}...".replace("\n", "\\n")
        print(colored(f"MicroGPT: {thought}\nCmd: {command}, Arg: \"{_argument}\"", "cyan"))
        user_input = input('Press enter to perform this action or abort by typing feedback: ')

        if len(user_input) > 0:
            agent.memorize(f"{mem}The user responded: {user_input}."\
                "Take this comment into consideration.")
            continue
        try:
            if command == "execute_python":
                _stdout = StringIO()
                with redirect_stdout(_stdout):
                    exec(argument)
                agent.memorize(f"{mem}{_stdout.getvalue()}")
            elif command == "execute_shell":
                result = subprocess.run(argument, capture_output=True, shell=True, check=False)
                agent.memorize(f"{mem}STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
            elif command == "web_search":
                agent.memorize(f"{mem}{ddg(argument, max_results=5)}")
            elif command == "web_scrape":
                with urlopen(argument) as response:
                    html = response.read()

                response_text = agent.chunked_summarize(
                    BeautifulSoup(
                        html,
                        features="lxml"
                    ).get_text(),
                    max_memory_item_size
                )

                agent.memorize(f"{mem}{response_text}")
            elif command == "read_file":
                with open(argument, "r") as f:
                    file_content = agent.chunked_summarize(f.read(), max_memory_item_size)
                agent.memorize(f"{mem}{file_content}")
        except Exception as e:
            agent.memorize(f"{mem}The command returned an error:\n{str(e)}\n"\
                "You should fix the command or code.")
