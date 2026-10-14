FROM python:3.11-slim

# Install system dependencies needed for PyMuPDF and image rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code, frontend assets, and data files
COPY . .

# Ensure data directory exists
RUN mkdir -p data

ENV PORT=8080
ENV PROJECT_ID=novartis-ai26hyd-803
ENV LOCATION=global

EXPOSE 8080

# Run FastAPI via Uvicorn using the PORT environment variable provided by Cloud Run
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8080}"]
