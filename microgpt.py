import re
import sys
import json
import tiktoken
import openai as o
from io import StringIO
import subprocess
from contextlib import redirect_stdout, redirect_stderr

MODEL = "gpt-4"
MAX_TOKENS = 8000
SYSTEM_PROMPT = "You are an autonomous agent that exexutes shell commands and Python code to achieve an objective."
INSTRUCTIONS = '''
Carefully consider the next command to execute and pass it to the agent. Execute Python code by setting "type" to Python or shell commands by setting "type" to shell.
All Python code must have an output "print" statement. Do NOT precede shell commands with an exclamation mark. Use only non-interactive shell commands.
Install packages with '!pip install <package>'
Respond with "DONE!" when the objective was accomplished. Otherwise, respond with a single JSON-encoded dict.
{
    "thought": "YOUR REASONING",
    "code": "[COMMAND LINE OR PYTHON CODE]",
    "type": "[shell OR python]"}
}
IMPORTANT: ALWAYS RESPOND ONLY WITH THIS EXACT JSON FORMAT. DOUBLE-CHECK YOUR RESPONSE TO MAKE SURE IT CONTAINS VALID JSON. DO NOT INCLUDE ANY EXTRA TEXT WITH THE RESPONSE.
'''

objective = sys.argv[1]

def install(package) -> str:
    return subprocess.check_output([sys.executable, "-m", "pip", "install", package]).decode('utf-8')

if __name__ == "__main__":
    memory = ""
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
            code = response["code"]
            type = response["type"]
        except Exception as e:
            print(f"Unable to parse response:\n{response_text}\n")
            memory += f"\nInvalid JSON response. Respond only with the correct JSON format! Error: {str(e)}\n"
            continue

        print(f"MicroGPT: {thought}")
        memory += f"\nThought:{thought}\nCode:{code}\nResult: "
        user_input = input('Press enter to perform this action or abort by typing feedback: ')

        if (len(user_input) > 0):
            memory += f"\nUser feedback: {user_input}\n"
            continue

        if (code) and (len(code) > 0):
            match = re.search("^!pip install (\S+)", code)
            if (match):
                try:
                    f = StringIO()
                    with redirect_stdout(f):
                        with redirect_stderr(f):
                            memory += install(match.group(1))
                except Exception as e:
                    memory += str(e)
            else:
                if (type == "python"):
                    f = StringIO()
                    try:
                        with redirect_stdout(f):
                            exec(code)
                        memory += f.getvalue()
                    except Exception as e:
                        memory += str(e)
                else:
                    result = subprocess.run(code, capture_output=True, shell=True)
                    memory += f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n"

            while(len(tiktoken.encoding_for_model(MODEL).encode(memory)) > MAX_TOKENS - 100):
                memory = memory[:len(memory)-100]

            if (len(tiktoken.encoding_for_model(MODEL).encode(memory)) > MAX_TOKENS - MAX_TOKENS/2):
                rs = o.ChatCompletion.create(
                    model=MODEL,
                    messages = [
                        {"role": "user", "content": f"Summarize the following memory contents of an autonomous agent using bullet points in first person to {MAX_TOKENS/2} tokens max.:\n{memory}"},
                        {"role": "user", "content": f"Retain tool outputs if possible."}, 
                    ])

                memory = rs['choices'][0]['message']['content']  