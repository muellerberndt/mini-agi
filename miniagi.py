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
import tiktoken
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
Supported commands are: internal_monologue, execute_python, execute_shell, read_file, web_search, web_scrape, talk_to_user, or done
The mandatory action format is:

<r>[YOUR_REASONING]</r><c>[COMMAND]</c>
[ARGUMENT]

ARGUMENT may have multiple lines if the argument is Python code.
Use only non-interactive shell commands.
web_scrape argument must be a single URL.
read_file argument must be a local file.
Python code run with execute_python must end with an output "print" statement.
Use your existing knowledge rather then web search when possible.
Use internal_monologue rather than Python to plan & organize thoughts.
Send the "done" command if the objective was achieved.
Your short-term memory is limited! Use temp files to deal with large amounts of data.
RESPOND WITH EXACTLY ONE THOUGHT/COMMAND/ARG COMBINATION.
DO NOT CHAIN MULTIPLE COMMANDS.
NO EXTRA TEXT BEFORE OR AFTER THE COMMAND.
DO NOT REPEAT PREVIOUSLY EXECUTED COMMANDS.

Each action returns an observation. Important: Observations may be summarized to fit into your limited memory.

Example actions:

<r>Think about how to organize the book into chapters</r><c>internal_monologue</c>
1. Chapter 1: Introduction
2. Chapter 2: Overview
(...)

<r>Search for websites with chocolate chip cookies recipe.</r><c>web_search</c>
chocolate chip cookies recipe

<r>Scrape information about chocolate chip cookies from the given URL.</r><c>web_scrape</c>
https://example.com/chocolate-chip-cookies

<r>I need to ask the user for guidance.</r><c>talk_to_user</c>
What is the URL of a website with chocolate chip cookies recipes?

<r>Write 'Hello, world!' to file</r><c>execute_python</c>
with open('hello_world.txt', 'w') as f:
    f.write('Hello, world!')

<r>The objective is complete.</r><c>done</c>
'''

CRITIC_PROMPT = '''
You are a critic reviewing the actions of an autonomous agent.
Evaluate the agent's performance.
Make concise suggestions for improvements, if any.
Provide recommended next steps.
Keep your response as short as possible.

Consider:
- Is agent taking reasonable steps to achieve the objective?
- Is agent making actual real-world progress towards the objective?
- Is the agent taking redundant or unnecessary steps?
- Is agent repeating itself or caught in a loop?
- Is the agent communicating results to the user?

EXAMPLE:

Criticism: The agent has been pretending to order pizza but has not actually
taken any real-world action. The agent should course-correct.

Recommended next steps:

1. Request an Uber API access token from the user.
2. Use the Uber API to order pizza.

AGENT OBJECTIVE:

{objective}

AGENT HISTORY:

{context}

'''

SUMMARY_HINT = "Retain information necessary for the agent to perform its task."\
    "Use short sentences and abbreviations."
EXTRA_SUMMARY_HINT = "Consider the agent's objective: '{summarizer_hint}' when"\
    " evaluating what information to include."

def update_memory(
        _agent: ThinkGPT,
        _action: str,
        _observation: str,
        summary: str,
        update_summary: bool = True
    ) -> str:
    """
    Updates the agent's memory with the last action performed and its observation.
    Optionally, updates the summary of agent's history as well.

    Args:
        _agent (ThinkGPT): The ThinkGPT instance whose memory is to be updated.
        _action (str): The action performed by the ThinkGPT instance.
        _observation (str): The observation made by the ThinkGPT 
            instance after performing the action.
        summary (str): The current summary of the agent's history.
        update_summary (bool, optional): Determines whether to update the summary. Defaults to True.

    Returns:
        str: The updated (or unchanged, depending on 'update_summary' value) 
        summary of the agent's history.
    """

    new_memory = f"ACTION\n{_action}\nRESULT:\n{_observation}\n"

    if update_summary:
        summary = summarizer.summarize(
            f"Current summary:\n{summary}\nAdd to summary:\n{new_memory}",
            max_memory_item_size,
            instruction_hint="Generate a new summary given the previous summary"\
                "of the agent's history and its last action. Maintain the entire history."\
                " Keep it short. Compress the summary using abbreviations."
            )

    _agent.memorize(new_memory)

    return summary


if __name__ == "__main__":

    agent = ThinkGPT(
        model_name=os.getenv("MODEL"),
        request_timeout=600,
        verbose=False
        )

    summarizer = ThinkGPT(
        model_name=os.getenv("SUMMARIZER_MODEL"),
        request_timeout=600,
        verbose=False
        )

    if len(sys.argv) != 2:
        print("Usage: miniagi.py <objective>")
        sys.exit(0)

    objective = sys.argv[1]
    max_context_size = int(os.getenv("MAX_CONTEXT_SIZE"))
    max_memory_item_size = int(os.getenv("MAX_MEMORY_ITEM_SIZE"))
    context = objective
    thought = ""
    observation = ""
    summarized_history = ""
    encoding = tiktoken.encoding_for_model(agent.model_name)

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

    while True:

        summary_len = len(encoding.encode(summarized_history))

        action_buffer = "\n".join(
                    agent.remember(
                    limit=32,
                    sort_by_order=True,
                    max_tokens=max_context_size - summary_len
                )
        )

        context = f"SUMMARY\n{summarized_history}\nPREV ACTIONS:\n{action_buffer}"

        if len(summarized_history) > 0 and ENABLE_CRITIC:
            with Spinner():
                criticism = agent.predict(
                        prompt=CRITIC_PROMPT.format(context=context, objective=objective)
                    )

            print(colored(criticism, "magenta"))

            criticism_len = len(encoding.encode(criticism))

            action_buffer = "\n".join(
                    agent.remember(
                    limit=32,
                    sort_by_order=True,
                    max_tokens=max_context_size - summary_len - criticism_len
                )
            )

            context = f"SUMMARY\n{summarized_history}\nPREV ACTIONS:\n{action_buffer}\n"\
                    f"REVIEW:\n{criticism}"

        if DEBUG:
            print(f"CONTEXT:\n{context}")

        with Spinner():

            try:
                response_text = agent.predict(
                    prompt=PROMPT.format(context=context, objective=objective)
                )

            except openai.error.InvalidRequestError as e:
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
                sys.exit(0)

            # Account for GPT-3.5 sometimes including an extra "done"
            if "done" in res_lines[-1]:
                res_line = res_lines[:-1]

            arg = "\n".join(res_lines[1:])

            # Remove unwanted code formatting backticks
            arg = arg.replace("```", "")

        except Exception as e:
            print(colored("Unable to parse response. Retrying...\n", "red"))
            observation = "This command was formatted"\
                " incorrectly. Use the correct syntax using the <r> and <c> tags."
            with Spinner():
                summarized_history = update_memory(
                    agent, res_lines[0],
                    observation,
                    summarized_history,
                    update_summary=False
                )
            continue

        _arg = arg.replace("\n", "\\n") if len(arg) < 64 else f"{arg[:64]}...".replace("\n", "\\n")
        action = f"{thought}\nCmd: {command}, Arg: \"{arg}\""
        abbreviated_action = f"{thought}\nCmd: {command}, Arg: \"{_arg}\""

        if command == "talk_to_user":
            print(colored(f"MiniAGI: {arg}", 'cyan'))
            user_input = input('Your response: ')
            observation = f"The user responded with: {user_input}."
            with Spinner():
                summarized_history = update_memory(
                    agent,
                    abbreviated_action,
                    observation,
                    summarized_history,
                    update_summary=True
                )
            continue

        print(colored(f"MiniAGI: {abbreviated_action}", "cyan"))

        if PROMPT_USER:
            user_input = input('Press enter to perform this action or abort by typing feedback: ')

            if len(user_input) > 0:
                observation = "The user responded with: {user_input}"
                with Spinner():
                    summarized_history = update_memory(
                        agent,
                        abbreviated_action,
                        observation,
                        summarized_history,
                        update_summary=False
                    )
                continue

        try:
            if command == "internal_monologue":
                observation = arg
                print(colored(f"MiniAGI is thinking to itself:\n{arg}", "green"))
            if command == "execute_python":
                _stdout = StringIO()
                with redirect_stdout(_stdout):
                    exec(arg)
                observation = _stdout.getvalue()
            elif command == "execute_shell":
                result = subprocess.run(arg, capture_output=True, shell=True, check=False)

                stdout = result.stdout.decode("utf-8")
                stderr = result.stderr.decode("utf-8")

                if len(stderr) > 0:
                    print(colored(f"Execution error: {stderr}", "red"))
                observation = f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            elif command == "web_search":
                observation = str(ddg(arg, max_results=5))
            elif command == "web_scrape":
                with urlopen(arg) as response:
                    html = response.read()
                with Spinner():
                    observation = BeautifulSoup(
                            html,
                            features="lxml"
                        ).get_text()
                observation = response_text
            elif command == "read_file":
                with Spinner():
                    with open(arg, "r") as f:
                        observation = f.read()
            elif command == "done":
                print("Objective achieved.")
                sys.exit(0)

            if len(encoding.encode(observation)) > max_memory_item_size:
                observation = summarizer.chunked_summarize(
                    observation, max_memory_item_size,
                    instruction_hint=SUMMARY_HINT +
                        EXTRA_SUMMARY_HINT.format(summarizer_hint=objective))

            with Spinner():
                summarized_history = update_memory(
                    agent,
                    action,
                    observation,
                    summarized_history,
                    update_summary=True
                )

        except Exception as e:
            if "context length" in str(e):
                print(colored(
                        f"{str(e)}\nTry decreasing MAX_CONTEXT_SIZE, MAX_MEMORY_ITEM_SIZE" \
                            " and SUMMARIZER_CHUNK_SIZE.",
                        "red"
                    )
                )

            print(colored(f"Execution error: {str(e)}", "red"))
            observation = f"The command returned an error:\n{str(e)}\n"

            with Spinner():
                summarized_history = update_memory(
                    agent,
                    action,
                    observation,
                    summarized_history,
                    update_summary=True
                )
