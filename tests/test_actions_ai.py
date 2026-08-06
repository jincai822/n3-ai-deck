from __future__ import annotations

import json
import subprocess
import urllib.error
from typing import Any

import pytest

from streamdock_n3.actions.ai import (
    CLIPBOARD_ARGV,
    CLIPBOARD_DETAIL,
    CLIPBOARD_TIMEOUT_SECONDS,
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    HTTP_TIMEOUT_SECONDS,
    MALFORMED_DETAIL,
    NO_CREDENTIAL_DETAIL,
    REQUEST_FAILED_DETAIL,
    REQUEST_TIMEOUT_DETAIL,
    AiTextPlugin,
)
from streamdock_n3.actions.contracts import (
    ActionContext,
    ActionPlugin,
    ActionResult,
    ActionStatus,
)

DEFAULT_KEY = "test-api-key"


def _context() -> ActionContext:
    return ActionContext("button.1.press", 1, "button", "press", 1_000_000)


def _full_config() -> dict[str, object]:
    return {
        "base_url": "https://example.invalid/v1",
        "model": "custom-model",
        "api_key_env": "MY_CUSTOM_KEY",
        "prompt": "Condense: {clipboard}",
    }


def _set_key(monkeypatch: pytest.MonkeyPatch, value: str = DEFAULT_KEY) -> None:
    monkeypatch.setenv(DEFAULT_API_KEY_ENV, value)


def _clipboard_fake(
    monkeypatch: pytest.MonkeyPatch,
    result: subprocess.CompletedProcess[bytes] | Exception,
    recorder: list[tuple[list[str], dict[str, Any]]] | None = None,
) -> None:
    def fake(argv: list[str], **kwargs: Any) -> Any:
        if recorder is not None:
            recorder.append((argv, kwargs))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("streamdock_n3.actions.ai.subprocess.run", fake)


def _clipboard_ok(text: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], 0, stdout=text.encode(), stderr=b"")


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _urlopen_fake(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: bytes | Exception,
    recorder: list[tuple[Any, float]] | None = None,
) -> None:
    def fake(request: Any, timeout: float) -> Any:
        if recorder is not None:
            recorder.append((request, timeout))
        if isinstance(result, Exception):
            raise result
        return _FakeResponse(result)

    monkeypatch.setattr("urllib.request.urlopen", fake)


def _ok_body(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def _recorded_request(recorder: list[tuple[Any, float]]) -> tuple[Any, float]:
    assert len(recorder) == 1
    return recorder[0]


def test_ai_text_metadata() -> None:
    metadata = AiTextPlugin().metadata()

    assert metadata.name == "ai_text"
    assert metadata.version == "1.0.0"


def test_ai_text_is_an_action_plugin() -> None:
    assert isinstance(AiTextPlugin(), ActionPlugin)


def test_ai_text_validate_config_accepts_empty_and_full_configs() -> None:
    plugin = AiTextPlugin()

    assert plugin.validate_config({}) == []
    assert plugin.validate_config(_full_config()) == []


@pytest.mark.parametrize(
    "config",
    (
        "xclip",
        None,
        42,
        {"base_url": ""},
        {"base_url": 42},
        {"base_url": "ftp://example.invalid"},
        {"model": ""},
        {"model": 42},
        {"prompt": ""},
        {"prompt": 42},
        {"api_key_env": ""},
        {"api_key_env": 42},
        {"api_key_env": "1BAD NAME"},
        {"api_key_env": "BAD NAME"},
        {"api_key_env": "ok-name"},
    ),
)
def test_ai_text_validate_config_rejects_invalid_configs(config: object) -> None:
    assert AiTextPlugin().validate_config(config) != []


def test_ai_text_missing_credential_is_a_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DEFAULT_API_KEY_ENV, raising=False)
    subprocess_calls: list[tuple[list[str], dict[str, Any]]] = []
    urlopen_calls: list[tuple[Any, float]] = []
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"), subprocess_calls)
    _urlopen_fake(monkeypatch, result=_ok_body("summary"), recorder=urlopen_calls)

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.ERROR
    assert result.detail == NO_CREDENTIAL_DETAIL
    assert subprocess_calls == []
    assert urlopen_calls == []


def test_ai_text_empty_credential_value_is_a_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch, "")
    urlopen_calls: list[tuple[Any, float]] = []
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"))
    _urlopen_fake(monkeypatch, result=_ok_body("summary"), recorder=urlopen_calls)

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.ERROR
    assert result.detail == NO_CREDENTIAL_DETAIL
    assert urlopen_calls == []


def test_ai_text_reads_custom_api_key_env_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_CUSTOM_KEY", "custom-key")
    recorder: list[tuple[Any, float]] = []
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"))
    _urlopen_fake(monkeypatch, result=_ok_body("summary"), recorder=recorder)

    result = AiTextPlugin().execute(_context(), _full_config())

    assert result.status is ActionStatus.OK
    request, _ = _recorded_request(recorder)
    assert request.get_header("Authorization") == "Bearer custom-key"


@pytest.mark.parametrize(
    ("clipboard_result", "clipboard_label"),
    (
        (FileNotFoundError("no such file"), "missing binary"),
        (subprocess.TimeoutExpired(["xclip"], 2), "timeout"),
        (subprocess.CompletedProcess([], 1, stdout=b"", stderr=b""), "nonzero exit"),
        (subprocess.CompletedProcess([], 0, stdout=b"", stderr=b""), "empty stdout"),
    ),
)
def test_ai_text_clipboard_failures_are_clipboard_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    clipboard_result: subprocess.CompletedProcess[bytes] | Exception,
    clipboard_label: str,
) -> None:
    del clipboard_label
    _set_key(monkeypatch)
    urlopen_calls: list[tuple[Any, float]] = []
    _clipboard_fake(monkeypatch, clipboard_result)
    _urlopen_fake(monkeypatch, result=_ok_body("summary"), recorder=urlopen_calls)

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.ERROR
    assert result.detail == CLIPBOARD_DETAIL
    assert urlopen_calls == []


def test_ai_text_clipboard_argv_is_fixed_and_shell_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)
    subprocess_calls: list[tuple[list[str], dict[str, Any]]] = []
    recorder: list[tuple[Any, float]] = []
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"), subprocess_calls)
    _urlopen_fake(monkeypatch, result=_ok_body("summary"), recorder=recorder)

    AiTextPlugin().execute(_context(), {})

    assert len(subprocess_calls) == 1
    argv, kwargs = subprocess_calls[0]
    assert list(argv) == list(CLIPBOARD_ARGV)
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == CLIPBOARD_TIMEOUT_SECONDS
    assert "shell" not in kwargs


def test_ai_text_http_error_status_is_request_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"))
    _urlopen_fake(
        monkeypatch,
        result=urllib.error.HTTPError(
            "https://example.invalid/v1/chat/completions", 401, "Unauthorized", {}, None
        ),
    )

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.ERROR
    assert result.detail == REQUEST_FAILED_DETAIL


def test_ai_text_network_error_is_request_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"))
    _urlopen_fake(monkeypatch, result=urllib.error.URLError(OSError("refused")))

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.ERROR
    assert result.detail == REQUEST_FAILED_DETAIL


def test_ai_text_http_timeout_is_request_timed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"))
    _urlopen_fake(monkeypatch, result=TimeoutError("timed out"))

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.ERROR
    assert result.detail == REQUEST_TIMEOUT_DETAIL


def test_ai_text_timeout_wrapped_in_urlerror_is_request_timed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"))
    _urlopen_fake(monkeypatch, result=urllib.error.URLError(TimeoutError("timed out")))

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.ERROR
    assert result.detail == REQUEST_TIMEOUT_DETAIL


def test_ai_text_malformed_json_is_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"))
    _urlopen_fake(monkeypatch, result=b"not json")

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.ERROR
    assert result.detail == MALFORMED_DETAIL


@pytest.mark.parametrize(
    "body",
    (
        b"{}",
        b'{"choices": "x"}',
        b'{"choices": []}',
        b'{"choices": ["x"]}',
        b'{"choices": [{"message": "x"}]}',
        b'{"choices": [{"message": {"content": 42}}]}',
        b'{"choices": [{"message": {"content": "   "}}]}',
    ),
)
def test_ai_text_missing_or_malformed_choices_is_malformed_response(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    _set_key(monkeypatch)
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"))
    _urlopen_fake(monkeypatch, result=body)

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.ERROR
    assert result.detail == MALFORMED_DETAIL


def test_ai_text_success_returns_the_first_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"))
    _urlopen_fake(
        monkeypatch,
        result=_ok_body("One sentence summary.\nSecond line must not appear."),
    )

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.OK
    assert result.plugin == "ai_text"
    assert result.detail == "One sentence summary."


def test_ai_text_success_truncates_a_long_first_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)
    _clipboard_fake(monkeypatch, _clipboard_ok("hello"))
    _urlopen_fake(monkeypatch, result=_ok_body("x" * 200))

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.OK
    assert len(result.detail) == 80
    assert result.detail == "x" * 80


def test_ai_text_success_request_carries_key_header_and_clipboard_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch, "secret-key")
    recorder: list[tuple[Any, float]] = []
    _clipboard_fake(monkeypatch, _clipboard_ok("clipboard text here"))
    _urlopen_fake(monkeypatch, result=_ok_body("summary"), recorder=recorder)

    result = AiTextPlugin().execute(_context(), {})

    assert result.status is ActionStatus.OK
    request, timeout = _recorded_request(recorder)
    assert request.full_url == f"{DEFAULT_BASE_URL}/chat/completions"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert request.get_header("Content-type") == "application/json"
    assert timeout == HTTP_TIMEOUT_SECONDS
    payload = json.loads(request.data)
    assert payload["model"] == DEFAULT_MODEL
    assert payload["messages"] == [
        {"role": "user", "content": DEFAULT_PROMPT.replace("{clipboard}", "clipboard text here")}
    ]


def test_ai_text_custom_config_overrides_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_CUSTOM_KEY", "custom-key")
    recorder: list[tuple[Any, float]] = []
    _clipboard_fake(monkeypatch, _clipboard_ok("clipboard text here"))
    _urlopen_fake(monkeypatch, result=_ok_body("summary"), recorder=recorder)

    result = AiTextPlugin().execute(_context(), _full_config())

    assert result.status is ActionStatus.OK
    request, _ = _recorded_request(recorder)
    assert request.full_url == "https://example.invalid/v1/chat/completions"
    payload = json.loads(request.data)
    assert payload["model"] == "custom-model"
    assert payload["messages"] == [
        {"role": "user", "content": "Condense: clipboard text here"}
    ]


def test_ai_text_execute_rejects_invalid_config_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)
    result = AiTextPlugin().execute(_context(), "not a config")

    assert result.status is ActionStatus.ERROR
    assert "config must be an object" in result.detail


def test_ai_text_never_raises_across_all_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)
    plugin = AiTextPlugin()
    failures: list[tuple[object, object, object]] = [
        ("not a config", _clipboard_ok("x"), _ok_body("y")),
        ({}, FileNotFoundError("xclip"), b"ignored"),
        ({}, subprocess.TimeoutExpired(["xclip"], 2), b"ignored"),
        ({}, _clipboard_ok("x"), urllib.error.URLError(OSError("refused"))),
        ({}, _clipboard_ok("x"), TimeoutError("timed out")),
        ({}, _clipboard_ok("x"), b"not json"),
    ]
    for config, clipboard_result, urlopen_result in failures:
        _clipboard_fake(monkeypatch, clipboard_result)
        _urlopen_fake(monkeypatch, result=urlopen_result)
        outcome = plugin.execute(_context(), config)
        assert isinstance(outcome, ActionResult)
