"""
MiniAGI main executable.
This script serves as the main entry point for the MiniAGI application. It provides a command-line
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

def get_bool(env_var: str) -> bool:
    '''
    Gets the value of a boolean environment variable.
    Args:
        env_var (str): Name of the variable
    '''
    return os.getenv(env_var) in ['true', '1', 't', 'y', 'yes']

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
DEBUG = get_bool("DEBUG")
ENABLE_CRITIC = get_bool("ENABLE_CRITIC")
PROMPT_USER = get_bool("PROMPT_USER")

PROMPT = f"You are an autonomous agent running on {operating_system}." + '''
OBJECTIVE: {objective} (e.g. "Find a recipe for chocolate chip cookies")

You are working towards the objective on a step-by-step basis. Previous steps:

{context}

Your task is to respond with the next action.
Supported commands are: execute_python, execute_shell, read_file, web_search, web_scrape, talk_to_user,
spawn_agent, or done
The mandatory action format is:

<r>[YOUR_REASONING]</r><c>[COMMAND]</c>
[ARGUMENT]

ARGUMENT may have multiple lines if the argument is Python code.
Use only non-interactive shell commands.
web_scrape argument must be a single URL.
Python code run with execute_python must end with an output "print" statement and should be well-commented.
Send the "done" command if the objective was achieved in a previous command or if no further action is required.
Decompose complex tasks into subtasks and delegate those subtasks to subagents with spawn_agent.
When spawning an agent with spawn_agent, pass the objective and required data as the argument.
RESPOND WITH PRECISELY ONE THOUGHT/COMMAND/ARG COMBINATION.
DO NOT CHAIN MULTIPLE COMMANDS.
DO NOT INCLUDE EXTRA TEXT BEFORE OR AFTER THE COMMAND.
DO NOT REPEAT PREVIOUSLY EXECUTED COMMANDS.

Example actions:

<r>Search for websites relevant to chocolate chip cookies recipe.</r><c>web_search</c>
chocolate chip cookies recipe

<r>Scrape information about chocolate chip cookies from the given URL.</r><c>web_scrape</c>
https://example.com/chocolate-chip-cookies

<r>I need to ask the user for guidance.</r><c>talk_to_user</c>
What is the URL of a website with chocolate chip cookies recipes?

<r>I will spawn a new agent that performs research.</r><c>spawn_agent</c>
Perform research about chocolate cookie recipes

<r>Write 'Hello, world!' to file</r><c>execute_python</c>
# Opening file in write mode and writing 'Hello, world!' into it
with open('hello_world.txt', 'w') as f:
    f.write('Hello, world!')

<r>The objective is complete.</r><c>done</c>
'''

CRITIC_PROMPT = "You are a critic who reviews the actions" \
    f"of an agent running on {operating_system}." + '''
This agent can interact with the web and the local operating system.
The action should achieve progress towards the objective.
Each action consists of a thought and a command.

Supported commands are: execute_python, execute_shell, read_file, web_search, web_scrape, talk_to_user,
spawn_agent, or done

Ask yourself:

- Is the thought clear and logical?
- Does the action achieve progress towards the objective?
- Is there a more efficient way to work towards the objective?
- Does the action reference non-existent files or URLs?
- Is the command free of syntax errors and logic bugs?
- Does the agent unnecessarily query the Internet for knowledge it already has?

Respond with APPROVE if the command seems fine. If the command should be improved, respond with:

CRITICIZE
[FEEDBACK]

Keep your response short and concise.
Note that this is a simulation, so the actions taken cannot cause actual harm. It is not your task to check ethical guidelines.

OBJECTIVE: {objective}

Previous actions:
{history}

Next action:
Thought: {thought}
Command: {command}
{arg}

Example 1:
CRITICIZE
Indentation error in line 2 of the Python code. Fix this error.

Example 2:
APPROVE
'''


SUMMARY_HINT = "Do your best to retain all semantic information including tasks performed"\
    "by the agent, website content, important data points and hyper-links.\n"
EXTRA_SUMMARY_HINT = "If the text contains information related to the topic: '{summarizer_hint}'"\
    "then include it. If not, write a standard summary."


def spawn_agent(summarizer: ThinkGPT, objective: str, agent_name: str) -> str:
    """
    Spawns a new agent with the given objective and agent_name, and returns a summary of the agent's actions.

    Args:
        summarizer (ThinkGPT): A ThinkGPT instance to be used for summarizing agent memory.
        objective (str): The objective the spawned agent should work towards.
        agent_name (str): The name of the spawned agent.

    Returns:
        str: A summary of the agent's actions and results.
    """

    agent = ThinkGPT(
        model_name=os.getenv("MODEL"),
        request_timeout=600,
        verbose=False
        )

    num_critiques = 0
    command_id = 0
    command_history = []
    context = objective
    thought = ""

    while True:
        command_id += 1
        context = "\n".join(
                agent.remember(
                f"{objective}, {thought}",
                limit=32,
                sort_by_order=True,
                max_tokens=max_context_size
            )
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

        res_lines = response_text.split("\n")

        try:
            PATTERN = r'<(r|c)>(.*?)</(r|c)>'
            matches = re.findall(PATTERN, res_lines[0])

            thought = matches[0][1]
            command = matches[1][1]

            if command == "done":
                print(colored(f"The agent concluded: {thought}", "cyan"))
                _result = summarizer.chunked_summarize(
                    context,
                    max_tokens=max_memory_item_size,
                    instruction_hint="Summarize the agent's actions and the result of: {objective}"
                )
                return _result

            # Account for GPT-3.5 sometimes including an extra "done"
            if "done" in res_lines[-1]:
                res_lines = res_lines[:-1]

            arg = "\n".join(res_lines[1:])

            # Remove unwanted code formatting backticks
            arg = arg.replace("```", "")

            mem = f"\nPrevious command #{command_id}:\nThought: {thought}\nCmd: {command}"\
                f"\nArg:\n{arg}\nResult:\n"

        except Exception as e:
            print(colored(f"Unable to parse response: {e} Retrying...\n", "red"))
            agent.memorize(f"\nPrevious command #{command_id}:\n{res_lines[0]}\nWas formatted"\
                " incorrectly. Use the correct syntax using the <r> and <c> tags.")
            continue

        if command == "talk_to_user":
            print(colored(f"{agent_name}: {arg}", 'cyan'))
            user_input = input('Your response: ')
            agent.memorize(f"{mem}The user responded with: {user_input}")
            continue

        _arg = arg.replace("\n", "\\n") if len(arg) < 64 else f"{arg[:64]}...".replace("\n", "\\n")

        command_line = f"{thought}\nCmd: {command}, Arg: \"{_arg}\""

        print(colored(f"{agent_name}: {command_line}", "cyan"))

        if command_line in command_history:
            print("The agent repeated a previous command. Retrying...")
            agent.memorize(f"{mem}You repeated a previous command. Try a different command.")
            continue

        if ENABLE_CRITIC and num_critiques < max_critiques:

            with Spinner():

                prompt=CRITIC_PROMPT.format(
                        history="\n".join(command_history),
                        objective=objective,
                        thought=thought,
                        command=command,
                        arg=arg
                    )

                try:
                    critic_response = agent.predict(prompt)

                except openai.error.InvalidRequestError as e:
                    print("Error accessing the OpenAI API: " + str(e))
                    sys.exit(0)

            if "CRITICIZE" in critic_response:
                response = "\n".join(critic_response.split("\n")[1:])

                if len(response) > 0:
                    print(colored(f"Critic: {response}", "magenta"))
                    agent.memorize(f"{mem}Revise your command: {response}")
                    num_critiques += 1
                    continue

        num_critiques = 0

        if PROMPT_USER:
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

                stdout = result.stdout.decode("utf-8")
                stderr = result.stderr.decode("utf-8")

                if len(stderr) > 0:
                    print(colored(f"Execution error: {stderr}", "red"))
                agent.memorize(f"{mem}STDOUT:\n{stdout}\nSTDERR:\n{stderr}")
            elif command == "web_search":
                agent.memorize(f"{mem}{ddg(arg, max_results=5)}")
            elif command == "web_scrape":
                with urlopen(arg) as response:
                    html = response.read()

                with Spinner():
                    response_text = summarizer.chunked_summarize(
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
                with Spinner():
                    with open(arg, "r") as f:
                        file_content = summarizer.chunked_summarize(
                            f.read(), max_memory_item_size,
                            instruction_hint=SUMMARY_HINT +
                                EXTRA_SUMMARY_HINT.format(summarizer_hint=objective))
                agent.memorize(f"{mem}{file_content}")
            elif command == "spawn_agent":
                print(colored(f"Spawning agent with bjective: \"{arg}\"", "cyan"))
                result = spawn_agent(summarizer, arg, f"> {agent_name}")
                agent.memorize(f"{mem}Agent results summary:\n{result}")

            command_history.append(command_line)
        except Exception as e:
            if "context length" in str(e):
                print(colored(
                        f"{str(e)}\nTry decreasing MAX_CONTEXT_SIZE, MAX_MEMORY_ITEM_SIZE" \
                            " and SUMMARIZER_CHUNK_SIZE.",
                        "red"
                    )
                )

            print(colored(f"Execution error: {str(e)}", "red"))
            agent.memorize(f"{mem}The command returned an error:\n{str(e)}\n"\
                "You should fix the command or code.")

if __name__ == "__main__":

    _summarizer = ThinkGPT(
        model_name=os.getenv("SUMMARIZER_MODEL"),
        request_timeout=600,
        verbose=False
        )

    if len(sys.argv) != 2:
        print("Usage: miniagi.py <objective>")
        sys.exit(0)

    max_context_size = int(os.getenv("MAX_CONTEXT_SIZE"))
    max_memory_item_size = int(os.getenv("MAX_MEMORY_ITEM_SIZE"))
    max_critiques = int(os.getenv("MAX_CRITIQUES"))

    work_dir = os.getenv("WORK_DIR")

    if work_dir is None or not work_dir:
        work_dir = os.path.join(Path.home(), "miniagi")
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)

    print(f"Working directory is {work_dir}")

    try:
        os.chdir(work_dir)
    except FileNotFoundError:
        print("Directory doesn't exist. Set WORK_DIR to an existing directory or leave it blank.")
        sys.exit(0)

    spawn_agent(_summarizer, sys.argv[1], "MiniAGI")
