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


PLANNER_PROMPT = f"You are the planner of an agent running on {operating_system}." + '''
Agent objective: {objective}
The agent is controlled by {model}
Agent capabilites

- Execute Python code
- Execute shell command
- Read file
- Search web
- Scrape URL
- Ask user

Create a numbered list consisting of short English sentences.
Write sentences of minimum length.
Plain English only, no commands.
Make the plan as simple as possible.
Use as few items as possible.
Consider the limitations of the agent:

- {model} memory limited to 4000 tokens

Whenever possible, use existing knowledge of {model} rather than accessing the Internet.

'''

AGENT_PROMPT = f"You are an autonomous agent running on {operating_system}." + '''
OBJECTIVE: {objective} (e.g. "Find a recipe for chocolate chip cookies")

Follow this action plan:

{action_plan}

Previous actions:

{context}

Respond with the next action according to the plan above.
Supported commands:
- execute_python
- execute_shell
- read_file
- web_search
- web_scrape
- talk_to_user
- revise_plan
- done
The mandatory format is:

<r>[YOUR_REASONING]</r><c>[COMMAND]</c>
[ARGUMENT]

ARGUMENT may have multiple lines if the argument is Python code.
Use only non-interactive shell commands.
web_scrape argument is a single URL.
Python code run with execute_python must end with an output "print" statement.
Send "done" command if no further action is required.
Send "revise_plan" command followed by a new action plan if the
current action plan needs to be updated.
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

<r>I need to revise the action plan because I cannot bake cookies</r><c>revise_plan</c>
1. Use web search to identify cookie recipes
2. Ask the user to bake cookies

<r>Write 'Hello, world!' to file</r><c>execute_python</c>
# Opening file in write mode and writing 'Hello, world!' into it
with open('hello_world.txt', 'w') as f:
    f.write('Hello, world!')

<r>The objective is complete.</r><c>done</c>
'''

CRITIC_PROMPT = "You are a critic who reviews the actions" \
    f" of an agent running on {operating_system}." + '''
Agent is controlled by {model}.
Agent can interact with the web and the local operating system.
Each action consists of 1 thought and 1 command.

Review the action according to the criteria:

The action should achieve progress towards the objective.
The agent should not perform redundant actions.
The agent should use non-interactive shell commands only.
The thought should be clear and logical.
The action should be effective in a real-world environment.
The action should reference only existent files and URLs.
The command and/or code should be free of syntax errors and logic bugs.
The agent should make use of the knowledge of its LLM.
The agent should not unnecessarily access the Internet.

Respond with APPROVE if the action seems fine. If the action should be improved, respond with:

CRITICIZE
[FEEDBACK]

Keep your response short and concise.
Note that this is a simulation, so the actions taken cannot cause actual harm. It is not your task to apply ethical guidelines.

OBJECTIVE: {objective}

The agent's action plan is:

{action_plan}

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
CRITICIZE
This command is redundant given previous commands. Move on to the next step.

Example 3:
APPROVE
'''


SUMMARY_HINT = "Attempt to retain all semantic information including tasks performed"\
    "by the agent, website content, important data points and hyper-links.\n"
EXTRA_SUMMARY_HINT = "If the text contains information related to: '{summarizer_hint}'"\
    "then include it. If not, write a standard summary."

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
    max_critiques = int(os.getenv("MAX_CRITIQUES"))
    context = objective

    work_dir = os.getenv("WORK_DIR")

    if work_dir is None or not work_dir:
        work_dir = os.path.join(Path.home(), "miniagi")
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)

    print(f"Working directory is {work_dir}")

    with Spinner():
        try:
            _prompt = PLANNER_PROMPT.format(objective=objective, model=agent.model_name)

            action_plan = agent.predict(
                prompt=_prompt
            )
        except openai.error.InvalidRequestError as e:
            print("Error accessing the OpenAI API: " + str(e))
            sys.exit(0)

    print(colored(f"Action plan:\n{action_plan}", "cyan"))

    try:
        os.chdir(work_dir)
    except FileNotFoundError:
        print("Directory doesn't exist. Set WORK_DIR to an existing directory or leave it blank.")
        sys.exit(0)

    num_critiques = 0
    command_id = 0
    command_history = []
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

        with Spinner():

            try:
                _prompt = AGENT_PROMPT.format(
                    context=context,
                    action_plan=action_plan,
                    objective=objective
                )

                if DEBUG:
                    print(f"AGENT PROMPT:\n\n{_prompt}")

                response_text = agent.predict(
                    prompt=_prompt
                )

            except openai.error.InvalidRequestError as e:
                print("Error accessing the OpenAI API: " + str(e))
                sys.exit(0)

        if DEBUG:
            print(f"AGENT RESPONSE:\n\n{response_text}")

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

            mem = f"\nPrevious command #{command_id}:\nThought: {thought}\nCmd: {command}"\
                f"\nArg:\n{arg}\nResult:\n"

        except Exception as e:
            print(colored("Unable to parse response. Retrying...\n", "red"))
            agent.memorize(f"\nPrevious command #{command_id}:\n{res_lines[0]}\n"\
                "Incorrect format. Use the correct syntax using the <r> and <c> tags.")
            continue

        if command == "talk_to_user":
            print(colored(f"MiniAGI: {arg}", 'cyan'))
            user_input = input('Your response: ')
            agent.memorize(f"{mem}The user responded with: {user_input}.")
            continue

        _arg = arg.replace("\n", "\\n") if len(arg) < 64 else f"{arg[:64]}...".replace("\n", "\\n")

        command_line = f"{thought}\nCmd: {command}, Arg: \"{_arg}\""

        print(colored(f"MiniAGI: {command_line}", "cyan"))

        if command_line in command_history:
            print("The agent repeated a previous command. Retrying...")
            agent.memorize(f"{mem}You repeated a previous command. Try a different command.")
            continue

        if ENABLE_CRITIC and num_critiques < max_critiques:

            with Spinner():

                _prompt=CRITIC_PROMPT.format(
                        model=agent.model_name,
                        history="\n".join(command_history),
                        objective=objective,
                        action_plan=action_plan,
                        thought=thought,
                        command=command,
                        arg=arg
                    )

                if DEBUG:
                    print(f"CRITIC PROMPT:\n\n{_prompt}")

                try:
                    critic_response = agent.predict(_prompt)

                except openai.error.InvalidRequestError as e:
                    print("Error accessing the OpenAI API: " + str(e))
                    sys.exit(0)

            if "CRITICIZE" in critic_response:
                response = "\n".join(critic_response.split("\n")[1:])

                if len(response) > 0:
                    print(colored(f"Critic: {response}", "magenta"))
                    agent.memorize(f"{mem}Revise your command: {response}.")
                    num_critiques += 1
                    continue

        num_critiques = 0

        if PROMPT_USER:
            user_input = input('Press enter to perform this action or abort by typing feedback: ')

            if len(user_input) > 0:
                agent.memorize(f"{mem}User responded: {user_input}."\
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
                    print(colored(f"Stderr: {stderr}", "red"))
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
            elif command == "revise_plan":
                action_plan = arg
                print(colored(f"Revised plan:\n{action_plan}", "cyan"))
            elif command == "done":
                print("Objective achieved.")
                sys.exit(0)

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
