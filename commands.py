"""
This module offers a collection of static methods that can execute different commands.
"""

import subprocess
from io import StringIO
from contextlib import redirect_stdout
from duckduckgo_search import DDGS


# pylint: disable=broad-exception-caught, exec-used, unspecified-encoding

class Commands:
    """
    A collection of static methods that can execute different commands.
    """

    @staticmethod
    def execute_command(command, arg) -> str:
        """
        Executes the command corresponding to the provided command string.

        Args:
            command (str): The command string representing the command to be executed.
            arg (str): The argument to be passed to the command.

        Returns:
            str: The result of the command execution, or an error 
                 message if an exception is raised during execution.
        """
        try:
            match command:
                case "memorize_thoughts":
                    result = Commands.memorize_thoughts(arg)
                case "execute_python":
                    result = Commands.execute_python(arg)
                case "execute_shell":
                    result = Commands.execute_shell(arg)
                case "web_search":
                    result = Commands.web_search(arg)
                case _:
                    result = f"Unknown command: {command}"
        except Exception as exception:
            result = f"Command returned an error:\n{str(exception)}"

        return result

    @staticmethod
    def memorize_thoughts(arg: str) -> str:
        """
        Simply returns the input string. Used to 'memorize' a thought.

        Args:
            arg (str): The input string.

        Returns:
            str: The input string.
        """
        return arg

    @staticmethod
    def execute_python(arg: str) -> str:
        """
        Executes the input Python code and returns the stdout.

        Args:
            arg (str): The input Python code.

        Returns:
            str: The stdout produced by the executed Python code.
        """
        _stdout = StringIO()
        with redirect_stdout(_stdout):
            exec(arg)

        return _stdout.getvalue()

    @staticmethod
    def execute_shell(arg: str) -> str:
        """
        Executes the input shell command and returns the stdout and stderr.

        Args:
            arg (str): The input shell command.

        Returns:
            str: The stdout and stderr produced by the executed shell command.
        """
        result = subprocess.run(arg, capture_output=True, shell=True, check=False)

        stdout = result.stdout.decode("utf-8")
        stderr = result.stderr.decode("utf-8")

        return f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"

    @staticmethod
    def web_search(arg: str) -> str:
        """
        Searches the web using DuckDuckGo and returns the results.

        Args:
            arg (str): The search query.

        Returns:
            str: The search results.
        """
        ddgs = DDGS()

        ddgs_text_gen = ddgs.text(arg)

        return str(list(ddgs_text_gen)[:5])
