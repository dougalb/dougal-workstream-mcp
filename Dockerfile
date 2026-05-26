FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORKSTREAM_DB_PATH=/data/workstream.db \
    WORKSTREAM_EXPORT_DIR=/exports \
    WORKSTREAM_CONFIG_PATH=/config/workstream.yaml \
    WORKSTREAM_PUBLIC_BASE_URL=http://localhost:8000 \
    WORKSTREAM_TRUST_PROXY_HEADERS=false

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && groupadd --system workstream \
    && useradd --system --gid workstream --home-dir /app workstream \
    && mkdir -p /data /exports /config /logs \
    && chown -R workstream:workstream /app /data /exports /config /logs

USER workstream

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"

CMD ["workstream", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
