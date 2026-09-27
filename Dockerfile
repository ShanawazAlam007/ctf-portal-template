FROM python:3.11-slim

# Prevent python from writing pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/backend

# Install OS dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy application code
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY config/ /app/config/

# Create logs directory
RUN mkdir -p /var/log/ctf-portal && chmod 777 /var/log/ctf-portal

# Make entrypoint and helper scripts executable
RUN chmod +x /app/backend/entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["/app/backend/entrypoint.sh"]
