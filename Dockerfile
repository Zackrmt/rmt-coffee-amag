FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy font files
COPY Poppins-Bold.ttf .
COPY Poppins-Light.ttf .
COPY Poppins-SemiBold.ttf .

# Copy the rest of the application
COPY . .

# Create health check endpoint
EXPOSE 8080

CMD ["python", "bot.py"]
