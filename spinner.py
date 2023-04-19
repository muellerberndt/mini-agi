"""
This module provides a spinning cursor effect for command-line interfaces.
See: https://stackoverflow.com/questions/4995733/how-to-create-a-spinning-command-line-cursor
"""

# pylint: disable=invalid-name

import sys
import time
import threading

class Spinner:
    """
    Implements the spinning cursor 
    """
    busy = False
    delay = 0.1

    @staticmethod
    def spinning_cursor():
        """
        A generator that yields a sequence of cursor characters for the spinning animation.
        
        Yields:
            str: A cursor character for the spinning animation.
        """
        while 1:
            for cursor in '|/-\\':
                yield cursor

    def __init__(self, delay=None):
        """
            Initialize a Spinner object with an optional custom delay between cursor frames.
            
            Args:
                delay (float, optional): The delay in seconds between cursor frames. 
                Defaults to None.
        """
        self.spinner_generator = self.spinning_cursor()
        if delay and float(delay):
            self.delay = delay

    def spinner_task(self):
        """
        The spinning cursor animation task. Writes the cursor character to stdout, flushes,
        sleeps for the specified delay, and then backspaces the cursor.
        """
        while self.busy:
            sys.stdout.write(next(self.spinner_generator))
            sys.stdout.flush()
            time.sleep(self.delay)
            sys.stdout.write('\b')
            sys.stdout.flush()

    def __enter__(self):
        self.busy = True
        threading.Thread(target=self.spinner_task).start()

    def __exit__(self, exception, value, tb):
        self.busy = False
        time.sleep(self.delay)
        if exception is not None:
            return False
        return True
