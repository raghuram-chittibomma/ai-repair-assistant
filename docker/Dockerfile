# Self-hosted API image (Phase 9). Build from repo root:
#   docker build -f docker/Dockerfile -t ai-repair-assistant-api .

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Manifest is required at runtime; documents stay user-supplied off-image.
COPY pyproject.toml README.md LICENSE ./
COPY corpus/manifest ./corpus/manifest
COPY src ./src

RUN pip install --upgrade pip && pip install .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"

CMD ["python", "-m", "repair_assistant.api.main"]
