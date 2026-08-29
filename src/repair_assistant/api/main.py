"""Run the HTTP API with uvicorn."""

from __future__ import annotations

import os

import uvicorn

from repair_assistant.ingest.env import load_dotenv_files


def run() -> None:
    load_dotenv_files()
    host = os.environ.get("REPAIR_API_HOST", "127.0.0.1")
    port = int(os.environ.get("REPAIR_API_PORT", "8080"))
    key = os.environ.get("REPAIR_API_KEY", "").strip()
    if not key and host not in {"127.0.0.1", "localhost", "::1"}:
        # ADR-0025 detector: D8 assumes loopback or an explicit LAN bind.
        print(
            "WARNING: REPAIR_API_KEY is empty and REPAIR_API_HOST is not loopback "
            f"({host}). LAN exposure is opt-in; set a key or bind 127.0.0.1 "
            "(review R5)."
        )
    uvicorn.run(
        "repair_assistant.api.app:app",
        host=host,
        port=port,
        reload=os.environ.get("REPAIR_API_RELOAD", "").lower() in {"1", "true", "yes"},
    )


if __name__ == "__main__":
    run()
