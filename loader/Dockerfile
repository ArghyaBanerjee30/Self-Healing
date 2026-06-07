FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy loader source
COPY loader/ ./loader/

# Default command — overridden by docker compose with actual --input and --project-name
ENTRYPOINT ["python", "-m", "loader.parse"]
