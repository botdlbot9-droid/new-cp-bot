FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    aria2 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install playwright (for stealth browser features)
RUN pip install playwright && playwright install chromium

# Copy bot files
COPY . .

# Create WVDs directory
RUN mkdir -p WVDs

# Expose port for Render
EXPOSE 8080

CMD ["python3", "bot.py"]
