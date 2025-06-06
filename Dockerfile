FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including Arial fonts
RUN apt-get update && apt-get install -y \
    fontconfig \
    ttf-mscorefonts-installer \
    && rm -rf /var/lib/apt/lists/*

# Accept EULA for MS fonts
RUN echo ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true | debconf-set-selections

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY src/ ./src/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Manila
ENV CURRENT_TIME="2025-06-06 16:24:19"
ENV CURRENT_USER="Zackrmt"

# Start the bot
CMD ["python", "src/bot.py"]
