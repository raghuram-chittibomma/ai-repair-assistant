"""LLM error taxonomy, retry, and degraded mode (review finding R36).

Before this, `openai.RateLimitError` and `APIStatusError` inherited from neither
`TimeoutError` nor `RuntimeError`, so they escaped every route handler and became
an HTTP 500. The review marked that **[inferred]**; the first test here reproduces
it by construction rather than assuming it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from repair_assistant.qa.generate import (
    ABSTAIN_LLM_UNAVAILABLE,
    LLMError,
    LLMRateLimitError,
    LLMRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
    OpenAIClient,
    ask,
    classify_llm_error,
)
from repair_assistant.retrieval.search import Hit, SearchResult
from repair_assistant.safety.models import Audience, SafetyAction, SafetyAssessment


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _openai_error(name: str, status: int = 429):
    import openai

    req = _request()
    if name == "RateLimitError":
        return openai.RateLimitError(
            "Rate limit reached for org-SECRET on requests per min",
            response=httpx.Response(429, request=req),
            body=None,
        )
    if name == "APIStatusError":
        return openai.APIStatusError(
            f"server error {status}",
            response=httpx.Response(status, request=req),
            body=None,
        )
    if name == "APIConnectionError":
        return openai.APIConnectionError(request=req)
    if name == "APITimeoutError":
        return openai.APITimeoutError(request=req)
    raise AssertionError(name)


def test_rate_limit_error_inherits_from_neither_timeout_nor_runtime():
    """The defect R36 describes, pinned so a future refactor cannot reintroduce it."""
    exc = _openai_error("RateLimitError")
    assert not isinstance(exc, TimeoutError)
    assert not isinstance(exc, RuntimeError)
    # ...which is why it must be classified before it reaches a route.
    assert isinstance(classify_llm_error(exc), RuntimeError)


@pytest.mark.parametrize(
    ("name", "status", "expected", "code"),
    [
        ("RateLimitError", 429, LLMRateLimitError, 429),
        ("APIStatusError", 503, LLMUnavailableError, 503),
        ("APIStatusError", 400, LLMRequestError, 502),
        ("APIConnectionError", 0, LLMUnavailableError, 503),
        ("APITimeoutError", 0, LLMTimeoutError, 504),
    ],
)
def test_classification_and_status_codes(name, status, expected, code):
    mapped = classify_llm_error(_openai_error(name, status))
    assert isinstance(mapped, expected)
    assert mapped.status_code == code
    if expected is not LLMTimeoutError:
        # Provider-derived messages are replaced; the timeout message is ours.
        assert mapped.client_message


def test_client_message_does_not_leak_provider_detail():
    mapped = classify_llm_error(_openai_error("RateLimitError"))
    assert "org-SECRET" in str(mapped), "the real detail should still be logged"
    assert "org-SECRET" not in mapped.client_message


class _FlakyCompletions:
    """Fails `failures` times with `exc`, then succeeds."""

    def __init__(self, exc, failures: int) -> None:
        self._exc = exc
        self._remaining = failures
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._exc
        message = MagicMock()
        message.content = "Recovered answer [1]."
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response


def _client_with(completions) -> OpenAIClient:
    client = OpenAIClient(api_key="k", model="m", timeout=1.0, max_attempts=3)
    fake = MagicMock()
    fake.chat.completions = completions
    client._client = lambda: fake  # type: ignore[method-assign]
    return client


def test_complete_records_token_usage_on_generation_span(monkeypatch):
    completions = _FlakyCompletions(_openai_error("RateLimitError"), failures=0)
    orig = completions.create

    def create_with_usage(**kwargs):
        response = orig(**kwargs)
        usage = MagicMock()
        usage.prompt_tokens = 20
        usage.completion_tokens = 8
        usage.total_tokens = 28
        response.usage = usage
        return response

    completions.create = create_with_usage  # type: ignore[method-assign]
    recorded: dict = {}
    monkeypatch.setattr(
        "repair_assistant.qa.generate.update_span",
        lambda _span, **kwargs: recorded.update(kwargs),
    )
    _client_with(completions).complete("sys", "user")
    assert recorded["usage"] == {"input": 20, "output": 8, "total": 28}


def test_transient_rate_limit_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "0")
    completions = _FlakyCompletions(_openai_error("RateLimitError"), failures=2)
    text = _client_with(completions).complete("sys", "user")
    assert text == "Recovered answer [1]."
    assert completions.calls == 3


def test_retry_gives_up_and_raises_the_classified_error(monkeypatch):
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "0")
    completions = _FlakyCompletions(_openai_error("RateLimitError"), failures=99)
    with pytest.raises(LLMRateLimitError):
        _client_with(completions).complete("sys", "user")
    assert completions.calls == 3


def test_timeouts_are_not_retried(monkeypatch):
    """The timeout is already the latency bound; retrying triples the wait."""
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "0")
    completions = _FlakyCompletions(_openai_error("APITimeoutError"), failures=99)
    with pytest.raises(LLMTimeoutError):
        _client_with(completions).complete("sys", "user")
    assert completions.calls == 1


def test_request_errors_are_not_retried(monkeypatch):
    """A 400 will fail identically every time."""
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "0")
    completions = _FlakyCompletions(_openai_error("APIStatusError", 400), failures=99)
    with pytest.raises(LLMRequestError):
        _client_with(completions).complete("sys", "user")
    assert completions.calls == 1


class _DeadLLM:
    model = "fake"

    def complete(self, system: str, user: str) -> str:
        raise LLMRateLimitError("OpenAI rate limit: org-SECRET quota exceeded")

    def stream(self, system: str, user: str):
        raise LLMUnavailableError("OpenAI returned 503: upstream")
        yield  # pragma: no cover - generator marker


def _hits() -> list[Hit]:
    return [
        Hit(
            doc_id="tech-sheet-w11320651",
            chunk_id="p1",
            text="F5E2 indicates a door lock fault. Inspect the strike.",
            page=12,
            kind="table_row",
            error_codes=["F5E2"],
            publication_number="W11320651",
            revision="A",
            score=0.9,
        )
    ]


def test_ask_degrades_to_cited_evidence_when_generation_fails():
    """Retrieval succeeded, so evidence beats an error page."""
    assessment = SafetyAssessment(
        action=SafetyAction.ALLOW, rule_id="allow", reason="", audience=Audience.OWNER
    )
    fit = MagicMock(ok=True, clarify_question="")
    with (
        patch("repair_assistant.qa.generate.assess_request", return_value=assessment),
        patch("repair_assistant.qa.generate.search") as search,
        patch("repair_assistant.retrieval.planner.check_evidence_fit", return_value=fit),
    ):
        search.return_value = SearchResult(query="q", hits=_hits(), fetched=1, filtered_out=0)
        result = ask(
            MagicMock(),
            MagicMock(),
            "What is F5E2?",
            audience=Audience.OWNER,
            llm=_DeadLLM(),  # type: ignore[arg-type]
        )

    assert result.abstain_code == ABSTAIN_LLM_UNAVAILABLE
    assert result.abstained is True
    assert result.citations, "the retrieved evidence must still be cited"
    assert "W11320651" in result.answer
    assert "org-SECRET" not in result.answer
    assert "org-SECRET" not in result.abstain_reason


def test_ask_stream_degrades_to_cited_evidence_when_generation_fails():
    from repair_assistant.qa.generate import ask_stream

    assessment = SafetyAssessment(
        action=SafetyAction.ALLOW, rule_id="allow", reason="", audience=Audience.OWNER
    )
    fit = MagicMock(ok=True, clarify_question="")
    with (
        patch("repair_assistant.qa.generate.assess_request", return_value=assessment),
        patch("repair_assistant.qa.generate.search") as search,
        patch("repair_assistant.retrieval.planner.check_evidence_fit", return_value=fit),
    ):
        search.return_value = SearchResult(query="q", hits=_hits(), fetched=1, filtered_out=0)
        events = list(
            ask_stream(
                MagicMock(),
                MagicMock(),
                "What is F5E2?",
                audience=Audience.OWNER,
                llm=_DeadLLM(),  # type: ignore[arg-type]
            )
        )

    done = events[-1]
    assert done["type"] == "done"
    assert done["abstain_code"] == ABSTAIN_LLM_UNAVAILABLE
    assert done["citations"]
    assert "org-SECRET" not in json_dump(events)


def json_dump(events) -> str:
    import json

    return json.dumps(events, default=str)


def test_llm_error_is_a_runtime_error():
    """So an unanticipated provider class degrades to a handled 503, not a 500."""
    assert issubclass(LLMError, RuntimeError)
    assert issubclass(LLMRateLimitError, LLMError)
    assert issubclass(LLMUnavailableError, LLMError)
    assert issubclass(LLMRequestError, LLMError)
