# Self-hosted API image (Phase 9). Build from repo root:
#   docker build -f docker/Dockerfile -t ai-repair-assistant-api .
#
# BGE is not baked in (image size). First embedder use downloads into HF_HOME
# unless you mount a pre-populated cache and set HF_HUB_OFFLINE=1. See
# docs/DEPLOYMENT.md.

FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/home/app/.cache/huggingface \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Manifest is required at runtime; documents stay user-supplied off-image.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY corpus/manifest ./corpus/manifest
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin app \
    && mkdir -p /home/app/.cache/huggingface \
    && chown -R app:app /app /home/app

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"

CMD ["python", "-m", "repair_assistant.api.main"]
