FROM python:3.13-slim

# Unbuffered output keeps App Runner logs in order. No bytecode keeps the image
# clean, and no pip cache keeps it small.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# requirements.txt is generated from uv.lock, so the image gets the same
# transitive versions the test suite ran against. Install it before the app
# source so a code change does not invalidate the dependency layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as an unprivileged numeric user. The app only reads its own code, so it
# needs no home directory and no write access to the image.
COPY --chown=10001:10001 app ./app
USER 10001:10001

# App Runner forwards traffic to this port.
EXPOSE 8000

# Docker and Compose can use this. App Runner uses its own configured health
# check against the same path.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

# App Runner terminates TLS and adds X-Forwarded-* headers. Trusting them is
# correct only because the container is not exposed directly to the internet.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
