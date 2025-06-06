FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including fonts
RUN apt-get update && apt-get install -y \
    fonts-poppins \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY src/ ./src/

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Start the bot
CMD ["python", "src/bot.py"]
