import os
import sys
import json
import openai
from duckduckgo_search import ddg
from io import StringIO
import subprocess
from contextlib import redirect_stdout
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

from memory import PineconeMemory

SYSTEM_PROMPT = "You are an autonomous agent who fulfills the user's objective."
INSTRUCTIONS = '''
Carefully consider your next command.
All Python code run with execute_python must have an output "print" statement.
Use only non-interactive shell commands.
When you have achieved the objective and do not need to perform any more actions, repond only with OBJECTIVE ACHIEVED
Otherwise, respond with a JSON-encoded dict containing one of the commands: execute_python, execute_shell, or web_search.
{"thought": "[REASONING]", "cmd": "[COMMAND]", "arg": "[ARGUMENT]"}
Example:
{"First, I will search for websites relevant to salami pizza.", "cmd": "web_search", "arg": "salami pizza"}
IMPORTANT: ALWAYS RESPOND ONLY WITH THIS EXACT JSON FORMAT. DOUBLE-CHECK YOUR RESPONSE TO MAKE SURE IT CONTAINS VALID JSON. DO NOT INCLUDE ANY EXTRA TEXT WITH THE RESPONSE.
'''

if __name__ == "__main__":

    model = os.getenv("MODEL")
    objective = sys.argv[1]
    memory = PineconeMemory()
    context = objective
    thought = "I awakened moments ago."

    while(True):
        print(f"Prompting {model}...")

        context = memory.get_context(f"{objective}, {thought}")

        print("CONTEXT: " + context)

        rs = openai.ChatCompletion.create(
            model=model,
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"OBJECTIVE:{objective}"},
                {"role": "user", "content": f"COMTEXT:\n{context}"},
                {"role": "user", "content": f"INSTRUCTIONS:\n{INSTRUCTIONS}"},
            ])

        response_text = rs['choices'][0]['message']['content']

        print(response_text)

        if "OBJECTIVE ACHIEVED" in response_text:
            print("Objective achieved.")
            quit()
        try:
            response = json.loads(response_text)
            thought = response["thought"]
            command = response["cmd"]
            arg = response["arg"]

            mem = f"Your thought: {thought}\nYour command: {command}\nCmd argument:\n{arg}\nResult:\n"

        except Exception as e:
            print(f"Unable to parse response:\n{str(e)}\Retrying...\n")
            continue

        _arg = arg.replace("\n", "\\n") if len(arg) < 64 else f"{arg[:64]}...".replace("\n", "\\n")
        print(f"MicroGPT: {thought}\nCmd: {command}, Arg: \"{_arg}\"")
        user_input = input('Press enter to perform this action or abort by typing feedback: ')

        if (len(user_input) > 0):
            memory.add(f"{mem}The user responded: {user_input}. Take this comment into consideration.")
            continue
        try:
            if (command == "execute_python"):
                f = StringIO()
                with redirect_stdout(f):
                    exec(arg)
                memory.add(f"{mem}{f.getvalue()}")
            elif command == "execute_shell":
                result = subprocess.run(arg, capture_output=True, shell=True)
                memory.add(f"{mem}STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
            elif command == "web_search":
                memory.add(f"{mem}{ddg(arg, max_results=5)}")
        except Exception as e:
                memory.add(f"{mem}The command returned an error:\n{str(e)}\nYou should fix the command.")
