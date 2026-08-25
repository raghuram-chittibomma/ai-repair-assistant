"""Run the HTTP API with uvicorn."""

from __future__ import annotations

import os

import uvicorn

from repair_assistant.ingest.env import load_dotenv_files


def run() -> None:
    load_dotenv_files()
    host = os.environ.get("REPAIR_API_HOST", "0.0.0.0")
    port = int(os.environ.get("REPAIR_API_PORT", "8080"))
    uvicorn.run(
        "repair_assistant.api.app:app",
        host=host,
        port=port,
        reload=os.environ.get("REPAIR_API_RELOAD", "").lower() in {"1", "true", "yes"},
    )


if __name__ == "__main__":
    run()
