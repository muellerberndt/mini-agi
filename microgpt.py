import sys
import json
import textwrap
import tiktoken
import openai as o
from duckduckgo_search import ddg
from io import StringIO
import subprocess
from contextlib import redirect_stdout

MODEL = "gpt-4"
MAX_TOKENS = 8000
SUMMARIZER_MODEL = "gpt-3.5-turbo"
SUMMARIZER_CHUNK_SIZE = 2500
SYSTEM_PROMPT = "You are an autonomous agent who fulfills the user's objective."
INSTRUCTIONS = '''
Carefully consider your next command.
All Python code run with execute_python must have an output "print" statement.
Use only non-interactive shell commands.
Respond with "DONE!" when the objective was accomplished.
Otherwise, respond with a JSON-encoded dict containing one of the commands: execute_python, execute_shell, or web_search.

{"thought": "[REASONING]", "cmd": "[COMMAND]", "arg": "[ARGUMENT]"}

Example:

{"First, I will search for websites relevant to salami pizza.", "cmd": "web_search", "arg": "salami pizza"}

IMPORTANT: ALWAYS RESPOND ONLY WITH THIS EXACT JSON FORMAT. DOUBLE-CHECK YOUR RESPONSE TO MAKE SURE IT CONTAINS VALID JSON. DO NOT INCLUDE ANY EXTRA TEXT WITH THE RESPONSE.
'''

objective = sys.argv[1]
memory = ""

def append_to_memory(content: str):
    global memory
    memory += f"\n{content}\n"

    num_tokens = len(tiktoken.encoding_for_model(SUMMARIZER_MODEL).encode(memory))

    if (num_tokens > MAX_TOKENS / 2):
        avg_chars_per_token = len(memory) / num_tokens

        chunk_size = int(avg_chars_per_token * SUMMARIZER_CHUNK_SIZE)
        chunks = textwrap.wrap(memory, chunk_size)
        summary_size = int(MAX_TOKENS / 2 / len(chunks))

        print(f"Summarizing memory in {len(chunks)} chunks of {chunk_size} characters")

        memory = ""

        for chunk in chunks:
            rs = o.ChatCompletion.create(
                model="SUMMARIZER_MODEL",
                messages = [
                    {"role": "user", "content": f"Shorten the following memory chunk of an autonomous agent from a first person perspective, {summary_size} tokens max."},
                    {"role": "user", "content": f"Do your best to retain all semantic information including tasks performed by the agent, website content, important data points and hyper-links:\n\n{chunk}"}, 
                ])
            memory += "CHUNK: " + rs['choices'][0]['message']['content']

if __name__ == "__main__":
    while(True):
        print(f"Prompting {MODEL}...")
        rs = o.ChatCompletion.create(
            model=MODEL,
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"OBJECTIVE:{objective}"},
                {"role": "user", "content": f"MEMORY:\n{memory}"},
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
            append_to_memory(f"Seems like you responded with the wrong JSON format.\nError: {str(e)}")
            continue

        _arg = arg.replace("\n", "\\n") if len(arg) < 64 else f"{arg[:64]}...".replace("\n", "\\n") 
        print(f"MicroGPT: {thought}\nCmd: {command}, Arg: \"{_arg}\"")
        append_to_memory(f"You thought: {thought}\nYour command: {command}\nCmd argument:\n{arg}\nResult:")
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
                append_to_memory(f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n")
            elif command == "web_search":
                append_to_memory(ddg(arg, max_results=5))
        except Exception as e:
                append_to_memory(f"The command returned an error:\n{str(e)}\nYou should fix the command.")
