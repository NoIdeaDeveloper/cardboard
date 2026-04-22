FROM python:3.12.9-slim

# Prevent Python from buffering stdout/stderr and writing .pyc files
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first (separate layer for better cache reuse)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install curl for the Docker health check
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend source
COPY backend/ ./

# Copy frontend assets
COPY frontend/ /app/frontend/

# Pre-create the data directory; the Docker volume will be mounted here at runtime
RUN mkdir -p /app/data

# Run as a non-root user for better security
RUN useradd --system --no-create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run migrations then start the server
CMD alembic upgrade head && \
    uvicorn main:app \
      --host 0.0.0.0 \
      --port 8000 \
      --log-level info \
      --access-log
