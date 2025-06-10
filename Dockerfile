FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    iputils-ping \
    snmp \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the requirements file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application files
COPY . .

# Expose the Flask web server port
EXPOSE 5000

# Run the monitor script
CMD ["python", "monitor.py"]
