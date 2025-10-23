FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends tesseract-ocr poppler-utils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements_railway.txt .
# Remove strict version pins to avoid install failures if versions are unavailable
RUN sed -E 's/==[0-9.]+//' requirements_railway.txt > /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p uploads

# The port the app runs on (Render requires port 10000 for Docker)
ENV PORT=10000

# Expose the port
EXPOSE ${PORT}

# Start the web service using the PORT env var. Use a timeout to avoid idle exits.
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT}", "--workers", "1", "--timeout", "120", "web_app:app"]
