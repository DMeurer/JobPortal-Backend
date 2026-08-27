FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv from PyPI rather than the astral.sh curl|sh bootstrap.
# Two reasons:
#   1. `curl ... | sh` swallows failure: if curl cannot verify TLS (which happens
#      behind an intercepting corporate proxy) it writes to stderr and pipes
#      nothing, so `sh` reads empty input and exits 0. The layer "succeeds" and
#      the build only fails later with a confusing `uv: not found` (exit 127).
#   2. PyPI is already required by this build, so this removes a second network
#      origin and its separate trust requirements.
RUN pip install --no-cache-dir uv

# Copy pyproject.toml first for better caching
COPY pyproject.toml .

# Install Python dependencies using uv
RUN uv pip install --system -r pyproject.toml

# Copy entrypoint script and make executable
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Copy application code
COPY . .

# Create a non-root user and change ownership
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose the port the app runs on
EXPOSE 8000

# Fix Permissions
RUN ["chmod", "+x", "/app/docker-entrypoint.sh"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
