"""
This module contains exceptions specific to MiniAGI.
"""

class InvalidLLMResponseError(Exception):
    """Exception raised when the LLM response can't be parsed.
    
    Attributes:
        None
    """
