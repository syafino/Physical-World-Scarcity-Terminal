# ===========================================
# PWST Multi-Stage Dockerfile
# ===========================================

# Base image with Python and system dependencies
FROM python:3.11-slim AS base

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies for PostGIS, GeoPandas
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgeos-dev \
    libproj-dev \
    libgdal-dev \
    gdal-bin \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files
COPY pyproject.toml README.md ./

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install .

# ===========================================
# API Server Target
# ===========================================
FROM base AS api

COPY src/ ./src/
COPY scripts/ ./scripts/

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ===========================================
# Streamlit UI Target
# ===========================================
FROM base AS ui

COPY src/ ./src/

EXPOSE 8501

CMD ["streamlit", "run", "src/ui/app.py", "--server.port=8501", "--server.address=0.0.0.0"]

# ===========================================
# Celery Worker Target
# ===========================================
FROM base AS worker

COPY src/ ./src/
COPY scripts/ ./scripts/

CMD ["celery", "-A", "src.scheduler", "worker", "--loglevel=info"]
