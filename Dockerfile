# Use the official Python base image
FROM python:3.10

# Copy requirements.txt into the container
COPY requirements.txt .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy script to copy env from shared folder during startup
COPY env.sh .
# Copy the rest of the application code
COPY *.py .

# Run the application
CMD ["echo", "use ./run.sh"]

