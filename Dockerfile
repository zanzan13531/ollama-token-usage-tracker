FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV MODE=proxy \
    DEVICE_NAME=default \
    OLLAMA_HOST=http://host.docker.internal:11435 \
    PROXY_PORT=11434 \
    DB_PATH=/data/usage.db \
    TIMEZONE=America/Los_Angeles

RUN mkdir -p /data

EXPOSE 11434

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:11434/stats')" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "11434"]
