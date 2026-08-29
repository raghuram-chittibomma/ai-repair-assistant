"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: Caps request bodies so a single call cannot flood the LLM (review R7).
MAX_QUERY_CHARS = 4000
MAX_MODEL_CHARS = 32
MAX_SERIAL_CHARS = 32


class CitationOut(BaseModel):
    index: int
    doc_id: str
    chunk_id: str
    label: str
    page: int | None = None


class SearchRequest(BaseModel):
    query: str = Field(max_length=MAX_QUERY_CHARS)
    model: str | None = Field(default=None, max_length=MAX_MODEL_CHARS)
    serial: str | None = Field(default=None, max_length=MAX_SERIAL_CHARS)
    limit: int = Field(default=8, ge=1, le=20)
    overfetch: int = Field(default=40, ge=1, le=200)


class SearchHitOut(BaseModel):
    doc_id: str
    chunk_id: str
    text: str
    page: int | None
    score: float
    publication_number: str | None = None
    error_codes: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHitOut]
    fetched: int
    filtered_out: int
    notice: str = ""
    abstain_code: str = ""


class AskRequest(BaseModel):
    question: str = Field(max_length=MAX_QUERY_CHARS)
    model: str | None = Field(default=None, max_length=MAX_MODEL_CHARS)
    serial: str | None = Field(default=None, max_length=MAX_SERIAL_CHARS)
    audience: Literal["owner", "technician"] = "owner"
    limit: int = Field(default=8, ge=1, le=20)
    overfetch: int = Field(default=40, ge=1, le=200)


class AskResponse(BaseModel):
    question: str
    answer: str
    abstained: bool
    abstain_reason: str = ""
    abstain_code: str = ""
    citations: list[CitationOut] = Field(default_factory=list)
    retrieval_count: int = 0
    safety_action: str = "allow"
    safety_notice: str = ""
    escalated: bool = False


class DiagnoseRequest(BaseModel):
    message: str = Field(max_length=MAX_QUERY_CHARS)
    model: str = Field(max_length=MAX_MODEL_CHARS)
    serial: str | None = Field(default=None, max_length=MAX_SERIAL_CHARS)
    audience: Literal["owner", "technician"] = "owner"
    session_id: str | None = None
    limit: int = Field(default=8, ge=1, le=20)
    overfetch: int = Field(default=40, ge=1, le=200)


class DiagnoseResponse(BaseModel):
    session_id: str
    turn: int
    assistant_message: str
    abstained: bool
    abstain_reason: str = ""
    abstain_code: str = ""
    citations: list[CitationOut] = Field(default_factory=list)
    retrieval_count: int = 0
    safety_action: str = "allow"
    safety_notice: str = ""
    escalated: bool = False


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    database: str
    embedder: str = "unknown"
    sessions: int = 0
