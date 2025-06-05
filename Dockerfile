FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for Pillow
RUN apt-get update && apt-get install -y \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot code
COPY . .

# Create fonts directory and copy fonts
RUN mkdir -p /usr/share/fonts/truetype/poppins

# Copy the Poppins font files
COPY Poppins-Bold.ttf Poppins-Light.ttf Poppins-SemiBold.ttf /usr/share/fonts/truetype/poppins/

# Update font cache
RUN fc-cache -f -v

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

# Run the bot
CMD ["python", "bot.py"]
