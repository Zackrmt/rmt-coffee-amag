FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies and create font directory
RUN apt-get update && apt-get install -y \
    fontconfig \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /usr/share/fonts/truetype/poppins

# Download Poppins fonts
RUN wget -O Poppins-Bold.ttf https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf \
    && wget -O Poppins-Light.ttf https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Light.ttf \
    && wget -O Poppins-SemiBold.ttf https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-SemiBold.ttf \
    && mv Poppins-*.ttf /usr/share/fonts/truetype/poppins/ \
    && fc-cache -f -v

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=10000
ENV HEALTH_CHECK_PORT=10001

# Run the bot
CMD ["python", "bot.py"]
