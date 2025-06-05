FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies and fonts
RUN apt-get update && apt-get install -y \
    fonts-poppins \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot code and fonts
COPY . .

# Make sure the fonts directory exists
RUN mkdir -p /app/fonts

# Copy Poppins fonts to the app directory
COPY fonts/*.ttf /app/fonts/

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the bot
CMD ["python", "bot.py"]
