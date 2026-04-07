# Stage 1: Build dependencies
FROM python:3.12-slim AS deps

WORKDIR /build
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime
FROM python:3.12-slim AS runtime

# Install openssl for PFX generation and certificate operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

COPY --from=deps /install /usr/local

WORKDIR /app
COPY src/ ./src/

# Create writable directories
RUN mkdir -p /app/data/logs /app/data/certs /app/data/backups \
    && chown -R appuser:appuser /app/data

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    SSL_DIR=/etc/letsencrypt \
    LOG_LEVEL=INFO

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "cert_manager.app:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
