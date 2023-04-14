# MicroGPT

A minimal autonomous agent.

## Rationale

The goal of this project was to create an agent with minimal amount of code and few external dependencies. It's completely up to the LLM to solve the objective using only Python code and shell commands.

## Installation

```
git clone 
cd micro-gpt
pip install -r requirements.txt
pythin micro-gpt <objective>
```

### Example

```
% python minigpt.py "Summarize the website https://en.wikipedia.org/wiki/Apple_cake and save the result to a text file on my Desktop."  
Prompting gpt-4...
MicroGPT: First, I need to install the necessary libraries to scrape and summarize the webpage.
Press enter to perform this action or abort by typing feedback: 
Prompting gpt-4...
MicroGPT: Now, I need to import the necessary libraries and define a function to scrape the website content
Press enter to perform this action or abort by typing feedback: 
Prompting gpt-4...
MicroGPT: I will now create a function to extract the text from the website content
Press enter to perform this action or abort by typing feedback: 
Prompting gpt-4...
MicroGPT: Now I need to import sumy, tokenize the text and perform the summarization
Press enter to perform this action or abort by typing feedback: 
Prompting gpt-4...
MicroGPT: Now I will save the summary_text to a text file on the Desktop.
Press enter to perform this action or abort by typing feedback: 
Prompting gpt-4...
MicroGPT: It seems the previous attempt to save the file to the Desktop failed due to the file path not being properly set. I will use the os library to get the correct path to the Desktop and try again
Press enter to perform this action or abort by typing feedback: 
Prompting gpt-4...
MicroGPT: The summary of the apple cake wikipedia page was successfully saved to a .txt file on the Desktop
```


