import os
import sys
import re
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

from memory import get_memory_instance

SYSTEM_PROMPT = "You are an autonomous agent who fulfills the user's objective."
INSTRUCTIONS = '''
Carefully consider your next command.
Supported commands are: execute_python, execute_shell, read_file, web_search, web_scrape, talk_to_user, or done
The mandatory response format is:

<r>[YOUR_REASONING]</r><c>[COMMAND]</c>
[ARGUMENT]

ARGUMENT may have multiple lines if the argument is Python code.

Example:

<r>Search for websites relevant to salami pizza.</r><c>web_search</c>
salami pizza

Example:

<r>Scrape information about Apples.</r><c>web_scrape</c>
https://en.wikipedia.org/wiki/Apple

Example:

<r>I need to ask the user for guidance.<r><c>talk_to_user</c>
What is URL of Domino's Pizza API?

Example:

<r>Write 'Hello, world!' to file</r><c>execute_python</c>
with open('hello_world.txt', 'w') as f:
    f.write('Hello, world!')

Use only non-interactive shell commands.
Python code run with execute_python must have an output "print" statement.
Send a separate "done" command *after* the objective was achieved.
IMPORTANT: RESPOND WITH PRECISELY ONE THOUGH/COMMAND/ARG COMBINATION.
DO NOT CHAIN MULTIPLE COMMANDS.
DO NOT INCLUDE EXTRA TEXT BEFORE OR AFTER THE COMMAND.
'''

if __name__ == "__main__":

    model = os.getenv("MODEL")

    if(len(sys.argv) != 2):
        print("Usage: microgpt.py <objective>")
        quit()

    objective = sys.argv[1]
    max_memory_item_size = int(os.getenv("MAX_MEMORY_ITEM_SIZE"))
    memory = get_memory_instance()
    context = objective
    thought = "I awakened moments ago."

    while(True):
        context = memory.get_context(f"{objective}, {thought}")

        if debug:
            print(f"CONTEXT:\n{context}")

        with Spinner():
            rs = openai.ChatCompletion.create(
                model=model,
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"OBJECTIVE:{objective}"},
                    {"role": "user", "content": f"CONTEXT:\n{context}"},
                    {"role": "user", "content": f"INSTRUCTIONS:\n{INSTRUCTIONS}"},
                ])

        response_text = rs['choices'][0]['message']['content']

        if debug:
            print(f"RAW RESPONSE:\n{response_text}")

        try:
            res_lines = response_text.split("\n")
            pattern = r'<(r|c)>(.*?)</(r|c)>'
            matches = re.findall(pattern, res_lines[0])

            thought = matches[0][1]
            command = matches[1][1]

            if command == "done":
                print("Objective achieved.")
                quit()
            
            # Account for GPT-3.5 sometimes including an extra "done"
            if "done" in res_lines[-1]:
                res_line = res_lines[:-1]

            arg = "\n".join(res_lines[1:])

            # Remove unwanted code formatting backticks
            arg = arg.replace("```", "")

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
            elif command == "done":
                print("Objective achieved.")
                quit()
        except Exception as e:
                memory.add(f"{mem}The command returned an error:\n{str(e)}\nYou should fix the command or code.")
