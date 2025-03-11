FROM python:3.11-slim

WORKDIR /app

# Copy our application code
COPY client.py .
COPY api_service.py .

# Copy requirements and install
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Create a directory for our data
RUN mkdir -p /app/rickmorty_data

# Run the application
CMD ["python", "api_service.py"]