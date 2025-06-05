FROM python:3.11.11-slim

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

# Set environment variables
ENV PORT=10000
ENV PYTHONUNBUFFERED=1

# Expose port for health check
EXPOSE ${PORT}

CMD ["python", "bot.py"]
