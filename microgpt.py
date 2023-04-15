import sys
import json
import tiktoken
import openai as o
import requests
from googlesearch import search
from io import StringIO
import subprocess
from contextlib import redirect_stdout

MODEL = "gpt-4"
MAX_TOKENS = 8000
SYSTEM_PROMPT = "You are an autonomous agent who fulfills the users' objective."
INSTRUCTIONS = '''
Carefully consider the next command to execute and pass it to the agent. Execute Python code by setting "type" to Python or shell commands by setting "type" to shell.
All Python code must have an output "print" statement. Do NOT precede shell commands with an exclamation mark. Use only non-interactive shell commands.
Respond with "DONE!" when the objective was accomplished.
Otherwise, respond with a JSON-encoded dict containing one of the commands: execute_python, execute_shell, get_url, or google. Use "get_url" to retrieve websites,

{"thought": "REASONING", "cmd": "COMMAND", "arg": "ARGUMENT"}

Example:

{"First, I will search for websites relevant to salami pizza.", "cmd": "google", "arg": "salami pizza"}

IMPORTANT: ALWAYS RESPOND ONLY WITH THIS EXACT JSON FORMAT. DOUBLE-CHECK YOUR RESPONSE TO MAKE SURE IT CONTAINS VALID JSON. DO NOT INCLUDE ANY EXTRA TEXT WITH THE RESPONSE.
'''

objective = sys.argv[1]
memory = ""

def append_to_memory(content: str):
    global memory
    memory += f"\n{content}\n"

    num_tokens = len(tiktoken.encoding_for_model(MODEL).encode(memory))

    if (num_tokens > MAX_TOKENS/2):
        approx_letters_per_token = len(memory) / num_tokens

        memory = memory[len(memory) - int((MAX_TOKENS - 100) * approx_letters_per_token):]

        rs = o.ChatCompletion.create(
            model=MODEL,
            messages = [
                {"role": "user", "content": f"Shorten the following memory of an autonomous agent from a first person perspective {MAX_TOKENS/2} tokens max.:\n{memory}"},
                {"role": "user", "content": f"Do your best to retain all semantic information, such as website content, important data points and hyper-links."}, 
            ])

        memory = rs['choices'][0]['message']['content']

if __name__ == "__main__":
    code = ""

    while(True):
        print(f"Prompting {MODEL}...")

        rs = o.ChatCompletion.create(
            model=MODEL,
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"OBJECTIVE:{objective}"},
                {"role": "user", "content": f"MEMORY:\n{memory}"},
                {"role": "user", "content": f"PREVIOUS_CODE:\n{code}"},
                {"role": "user", "content": f"INSTRUCTIONS:\n{INSTRUCTIONS}"},
            ])

        response_text = rs['choices'][0]['message']['content']

        if response_text == "DONE!":
            quit()
        try:
            response = json.loads(response_text)
            thought = response["thought"]
            command = response["cmd"]
            arg = response["arg"]
        except Exception as e:
            print(f"Unable to parse response:\n{response_text}\n")
            append_to_memory(f"Invalid JSON response. Respond only with the correct JSON format! Error: {str(e)}")
            continue

        print(f"MicroGPT: {thought}")
        append_to_memory(f"THOUGHT: {thought}\nCMD: {command}\nARG:\n{arg}\nRESULT:")
        user_input = input('Press enter to perform this action or abort by typing feedback: ')

        if (len(user_input) > 0):
            append_to_memory(f"User feedback: {user_input}")
            continue
        try:
            if (command == "execute_python"):
                f = StringIO()
                with redirect_stdout(f):
                    exec(arg)
                append_to_memory(f.getvalue())
            elif command == "execute_shell":
                result = subprocess.run(arg, capture_output=True, shell=True)
                append_to_memory("STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n")
            elif command == "google":
                append_to_memory("Search results:")
                for j in search(arg, num=5):
                    append_to_memory(j)
                print("Google completed")
            elif command == "get_url":
                response = requests.get(arg)
                print(response)
                append_to_memory(f"STATUS CODE: {response.status_code}\nCONTENT:\n{response.content}")
        except Exception as e:
                append_to_memory(f"Error executing command: {str(e)}")
