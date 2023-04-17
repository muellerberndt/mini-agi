import os
import sys
import json
import openai
from termcolor import colored
from bs4 import BeautifulSoup
from urllib.request import urlopen
from duckduckgo_search import ddg
from io import StringIO
from contextlib import redirect_stdout
import subprocess
from dotenv import load_dotenv
from spinner import Spinner

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

debug = True if os.getenv("DEBUG") in ['true', '1', 't', 'y', 'yes'] else False

from memory import RedisMemory

SYSTEM_PROMPT = "You are an autonomous agent who fulfills the user's objective."
INSTRUCTIONS = '''
Carefully consider your next command.
All Python code run with execute_python must have an output "print" statement.
Use only non-interactive shell commands.
When you have achieved the objective, respond ONLY with the plaintext OBJECTIVE ACHIEVED (no JSON)
Otherwise, respond with a JSON-encoded dict containing one of the commands: execute_python, execute_shell, read_file, web_search, web_scrape, or talk_to_user
Important: Escape all occurrences of \\n in Python code with \\\\n
{"thought": "[REASONING]", "cmd": "[COMMAND]", "arg": "[ARGUMENT]"}
Examples:
{"First, I will search for websites relevant to salami pizza.", "cmd": "web_search", "arg": "salami pizza"}
{"I am going to scrape information about Apples.", "cmd": "web_scrape", "arg": "https://en.wikipedia.org/wiki/Apple"}
{"Showing results to the user", "cmd": "talk_to_user", "arg": "[My results]. Did I achieve my objective?"}
{"I need to ask the user for guidance", "cmd": "talk_to_user", "arg": "What is URL of Domino's Pizza API?"}
IMPORTANT: ALWAYS RESPOND ONLY WITH THIS EXACT JSON FORMAT. DOUBLE-CHECK YOUR RESPONSE TO MAKE SURE IT CONTAINS VALID JSON. DO NOT INCLUDE ANY EXTRA TEXT WITH THE RESPONSE.
'''

if __name__ == "__main__":

    model = os.getenv("MODEL")

    if(len(sys.argv) != 2):
        print("Usage: microgpt.py <objective>")
        quit()

    objective = sys.argv[1]
    max_memory_item_size = int(os.getenv("MAX_MEMORY_ITEM_SIZE"))
    memory = RedisMemory()
    context = objective
    thought = "I awakened moments ago."

    while(True):
        # print(f"Prompting {model}...")

        context = memory.get_context(f"{objective}, {thought}")
        
        if debug:
            print(f"CONTEXT:\n{context}")

        with Spinner():
            rs = openai.ChatCompletion.create(
                model=model,
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"OBJECTIVE:{objective}"},
                    {"role": "user", "content": f"COMTEXT:\n{context}"},
                    {"role": "user", "content": f"INSTRUCTIONS:\n{INSTRUCTIONS}"},
                ])

        response_text = rs['choices'][0]['message']['content']

        if debug:
            print(f"RAW RESPONSE:\n{response_text}")

        if response_text == "OBJECTIVE ACHIEVED":
            print("Objective achieved.")
            quit()
        try:
            response = json.loads(response_text)
            thought = response["thought"]
            command = response["cmd"]
            arg = response["arg"]

            mem = f"Your thought: {thought}\nYour command: {command}\nCmd argument:\n{arg}\nResult:\n"

        except Exception as e:
            print(colored("Unable to parse response. Retrying...\n", "red"))
            continue

        if (command == "talk_to_user"):
            print(colored(f"MicroGPT: {arg}", 'cyan'))
            user_input = input('Your response: ')
            memory.add(f"{mem}The user responded with: {user_input}.")
            continue

        _arg = arg.replace("\n", "\\n") if len(arg) < 64 else f"{arg[:64]}...".replace("\n", "\\n")
        print(colored(f"MicroGPT: {thought}\nCmd: {command}, Arg: \"{_arg}\"", "cyan"))
        user_input = input('Press enter to perform this action or abort by typing feedback: ')

        if (len(user_input) > 0):
            memory.add(f"{mem}The user responded: {user_input}. Take this comment into consideration.")
            continue
        try:
            if (command == "execute_python"):
                _stdout = StringIO()
                with redirect_stdout(_stdout):
                    exec(arg)
                memory.add(f"{mem}{_stdout.getvalue()}")
            elif command == "execute_shell":
                result = subprocess.run(arg, capture_output=True, shell=True)
                memory.add(f"{mem}STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
            elif command == "web_search":
                memory.add(f"{mem}{ddg(arg, max_results=5)}")
            elif command == "web_scrape":
                html = urlopen(arg).read()
                response_text = memory.summarize_memory_if_large(BeautifulSoup(html, features="lxml").get_text(), max_memory_item_size)
                memory.add(f"{mem}{response_text}")
            elif command == "read_file":
                f = open(arg, "r")
                file_content = memory.summarize_memory_if_large(f.read(), max_memory_item_size)
                memory.add(f"{mem}{file_content}")
        except Exception as e:
                memory.add(f"{mem}The command returned an error:\n{str(e)}\nYou should fix the command.")
