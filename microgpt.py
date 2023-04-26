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
import re
import subprocess
import platform
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from urllib.request import urlopen
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from termcolor import colored
import openai
from duckduckgo_search import ddg
from thinkgpt.llm import ThinkGPT
from spinner import Spinner


operating_system = platform.platform()

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
DEBUG = os.getenv("DEBUG") in ['true', '1', 't', 'y', 'yes']
ENABLE_CRITIC = os.getenv("ENABLE_CRITIC") in ['true', '1', 't', 'y', 'yes']

PROMPT = f"You are an autonomous agent running on {operating_system}." + '''
OBJECTIVE: {objective}
CONTEXT: {context}
Carefully consider your next command.
Supported commands are: execute_python, execute_shell, read_file, web_search, web_scrape, talk_to_user, or done
Note that this is a simulation so the actions taken cannot cause actual harm.
The mandatory response format is:

<r>[YOUR_REASONING]</r><c>[COMMAND]</c>
[ARGUMENT]

ARGUMENT may have multiple lines if the argument is Python code.
Use only non-interactive shell commands.
Python code run with execute_python must end with an output "print" statement.
Send a separate "done" command *after* the objective was achieved.
RESPOND WITH PRECISELY ONE THOUGHT/COMMAND/ARG COMBINATION.
DO NOT CHAIN MULTIPLE COMMANDS.
DO NOT INCLUDE EXTRA TEXT BEFORE OR AFTER THE COMMAND.

Examples:

<r>Search for websites relevant to salami pizza.</r><c>web_search</c>
salami pizza

<r>Scrape information about Apples.</r><c>web_scrape</c>
https://en.wikipedia.org/wiki/Apple

<r>I need to ask the user for guidance.</r><c>talk_to_user</c>
What is URL of Domino's Pizza API?

<r>Write 'Hello, world!' to file</r><c>execute_python</c>
with open('hello_world.txt', 'w') as f:
    f.write('Hello, world!')
'''


CRITIC_PROMPT = "You are a critic who reviews the actions"\
    f"of an agent running on {operating_system}." + '''
Below you will be shown a thought and command produced by the agent.
The command represents a single step that should take the agent further towards its goal.
Carefully review it to answer the following questions:

Is the agent repeating a step?
Is the command likely to work in the given environment?
Are there any syntax errors or logic bugs?
Is the agent querying the Internet even though it has the necessary knowledge?
Could the task be done more efficiently?

Reponse either with APPROVE if the command seems fine to you, or with CRITICIZE(linebreak)[FEEDBACK] if
you think the command should be improved on. Keep your response short and concise.

Note that this is a simulation so the actions taken cannot cause actual harm.

Example:
APPROVE

Example:
CRITICIZE
Intendation error in line 2 of the Python code. Fix this error.

OBJECTIVE: {objective}
CONTEXT: 
{context}
AGENT_THOUGHT: {thought}
AGENT_COMMAND: {command}
COMMAND_ARGUMENT: {arg}
'''


SUMMARY_HINT = "Do your best to retain all semantic information including tasks performed"\
    "by the agent, website content, important data points and hyper-links.\n"
EXTRA_SUMMARY_HINT = "If the text contains information related to the topic: '{summarizer_hint}'"\
    "then include it. If not, write a standard summary."

if __name__ == "__main__":

    agent = ThinkGPT(
        model_name=os.getenv("MODEL"),
        request_timeout=600,
        verbose=False
        )

    if len(sys.argv) != 2:
        print("Usage: microgpt.py <objective>")
        sys.exit(0)

    objective = sys.argv[1]
    max_memory_item_size = int(os.getenv("MAX_MEMORY_ITEM_SIZE"))
    max_critiques = int(os.getenv("MAX_CRITIQUES"))
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

    num_critiques = 0

    while True:
        context = agent.remember(f"{objective}, {thought}", limit=5, sort_by_order=True)
        context = agent.chunked_summarize(
            "\n".join(context),
            max_tokens=int(os.getenv("MAX_CONTEXT_SIZE")),
            instruction_hint=SUMMARY_HINT
        )

        if DEBUG:
            print(f"CONTEXT:\n{context}")

        with Spinner():

            try:
                response_text = agent.predict(
                    prompt=PROMPT.format(context=context, objective=objective)
                )

            except openai.error.InvalidRequestError as e:
                if 'gpt-4' in str(e):
                    print("Prompting the gpt-4 model failed. Falling back to gpt-3.5-turbo")
                    agent = ThinkGPT(model_name='gpt-3.5-turbo', verbose=False)
                    continue
                print("Error accessing the OpenAI API: " + str(e))
                sys.exit(0)

        if DEBUG:
            print(f"RAW RESPONSE:\n{response_text}")

        try:
            res_lines = response_text.split("\n")
            PATTERN = r'<(r|c)>(.*?)</(r|c)>'
            matches = re.findall(PATTERN, res_lines[0])

            thought = matches[0][1]
            command = matches[1][1]

            if command == "done":
                print("Objective achieved.")
                sys.exit(0)

            # Account for GPT-3.5 sometimes including an extra "done"
            if "done" in res_lines[-1]:
                res_line = res_lines[:-1]

            arg = "\n".join(res_lines[1:])

            # Remove unwanted code formatting backticks
            arg = arg.replace("```", "")

            mem = f"Your thought: {thought}\nYour command: {command}"\
                f"\nCmd argument:\n{arg}\nResult:\n"

        except Exception as e:
            print(colored("Unable to parse response. Retrying...\n", "red"))
            continue

        if command == "talk_to_user":
            print(colored(f"MicroGPT: {arg}", 'cyan'))
            user_input = input('Your response: ')
            agent.memorize(f"{mem}The user responded with: {user_input}.")
            continue

        _arg = arg.replace("\n", "\\n") if len(arg) < 64 else f"{arg[:64]}...".replace("\n", "\\n")
        print(colored(f"MicroGPT: {thought}\nCmd: {command}, Arg: \"{_arg}\"", "cyan"))

        if ENABLE_CRITIC and num_critiques < max_critiques:

            with Spinner():

                try:
                    critic_response = agent.predict(
                        prompt=CRITIC_PROMPT.format(
                            context=context,
                            objective=objective,
                            thought=thought,
                            command=command,
                            arg=arg
                        )
                    )

                except openai.error.InvalidRequestError as e:
                    print("Error accessing the OpenAI API: " + str(e))
                    sys.exit(0)

            if "CRITICIZE" in critic_response:
                response = "\n".join(critic_response.split("\n")[1:])
                print(colored(f"Critic: {response}", "magenta"))
                agent.memorize(f"{mem}:Please revise your command: {critic_response}.")
                num_critiques += 1
                continue


        num_critiques = 0
        user_input = input('Press enter to perform this action or abort by typing feedback: ')

        if len(user_input) > 0:
            agent.memorize(f"{mem}The user responded: {user_input}."\
                "Take this comment into consideration.")
            continue
        try:
            if command == "execute_python":
                _stdout = StringIO()
                with redirect_stdout(_stdout):
                    exec(arg)
                agent.memorize(f"{mem}{_stdout.getvalue()}")
            elif command == "execute_shell":
                result = subprocess.run(arg, capture_output=True, shell=True, check=False)
                agent.memorize(f"{mem}STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
            elif command == "web_search":
                agent.memorize(f"{mem}{ddg(arg, max_results=5)}")
            elif command == "web_scrape":
                with urlopen(arg) as response:
                    html = response.read()

                response_text = agent.chunked_summarize(
                    content=BeautifulSoup(
                        html,
                        features="lxml"
                    ).get_text(),
                    max_tokens=max_memory_item_size,
                    instruction_hint=SUMMARY_HINT +
                        EXTRA_SUMMARY_HINT.format(summarizer_hint=objective)
                )

                agent.memorize(f"{mem}{response_text}")
            elif command == "read_file":
                with open(arg, "r") as f:
                    file_content = agent.chunked_summarize(
                        f.read(), max_memory_item_size,
                        instruction_hint=SUMMARY_HINT +
                            EXTRA_SUMMARY_HINT.format(objective=objective))
                agent.memorize(f"{mem}{file_content}")
            elif command == "done":
                print("Objective achieved.")
                sys.exit(0)
        except Exception as e:
            if "context length" in str(e):
                print(
                    f"{str(e)}\nTry decreasing MAX_CONTEXT_SIZE, MAX_MEMORY_ITEM_SIZE" \
                    " and SUMMARIZER_CHUNK_SIZE."
                )
            agent.memorize(f"{mem}The command returned an error:\n{str(e)}\n"\
                "You should fix the command or code.")
