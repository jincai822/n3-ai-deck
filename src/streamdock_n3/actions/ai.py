"""AiTextPlugin: stdlib-only OpenAI-compatible summarize plugin for M4.

P2 of the M4 design (section 4.4 of
docs/superpowers/specs/2026-08-05-m4-ai-workflow-design.md): reads the X11
clipboard with a fixed argv (no shell), calls an OpenAI-compatible
`/chat/completions` endpoint, and returns a one-sentence summary as a
structured ActionResult. Every failure path returns a structured result and
never raises; the API key and the full AI payload are never logged.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from collections.abc import Sequence

from streamdock_n3.actions.contracts import (
    ActionContext,
    ActionResult,
    ActionStatus,
    PluginMetadata,
)

DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
DEFAULT_MODEL = "moonshot-v1-8k"
DEFAULT_API_KEY_ENV = "N3_AI_DECK_API_KEY"
DEFAULT_PROMPT = "Summarize the following text into one sentence: {clipboard}"
CLIPBOARD_PLACEHOLDER = "{clipboard}"

CLIPBOARD_ARGV: Sequence[str] = ("xclip", "-selection", "clipboard", "-o")
CLIPBOARD_TIMEOUT_SECONDS = 2
HTTP_TIMEOUT_SECONDS = 10
MAX_DETAIL_CHARS = 80

NO_CREDENTIAL_DETAIL = "ai: no credential in environment"
CLIPBOARD_DETAIL = "ai: clipboard unavailable"
REQUEST_FAILED_DETAIL = "ai: request failed"
REQUEST_TIMEOUT_DETAIL = "ai: request timed out"
MALFORMED_DETAIL = "ai: malformed response"


class AiTextPlugin:
    """Summarize the clipboard via an OpenAI-compatible endpoint."""

    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            "ai_text",
            "1.0.0",
            "Summarize clipboard text via an OpenAI-compatible endpoint",
        )

    def validate_config(self, config: object) -> list[str]:
        problems: list[str] = []
        if not isinstance(config, dict):
            return ["config must be an object"]
        base_url = config.get("base_url")
        if base_url is not None and (
            not isinstance(base_url, str)
            or not base_url
            or not (base_url.startswith("http://") or base_url.startswith("https://"))
        ):
            problems.append("config.base_url must be an http(s) URL")
        for key in ("model", "prompt"):
            value = config.get(key)
            if value is not None and (not isinstance(value, str) or not value):
                problems.append(f"config.{key} must be a non-empty string")
        api_key_env = config.get("api_key_env")
        if api_key_env is not None:
            if not isinstance(api_key_env, str) or not api_key_env:
                problems.append("config.api_key_env must be a non-empty string")
            elif not _is_env_name(api_key_env):
                problems.append(
                    "config.api_key_env must be a valid environment variable name"
                )
        return problems

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        del context
        problems = self.validate_config(config)
        if problems:
            return self._error("; ".join(problems))
        cfg = config if isinstance(config, dict) else {}
        base_url = str(cfg.get("base_url", DEFAULT_BASE_URL))
        model = str(cfg.get("model", DEFAULT_MODEL))
        api_key_env = str(cfg.get("api_key_env", DEFAULT_API_KEY_ENV))
        prompt = str(cfg.get("prompt", DEFAULT_PROMPT))

        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            return self._error(NO_CREDENTIAL_DETAIL)

        clipboard = self._read_clipboard()
        if not clipboard:
            return self._error(CLIPBOARD_DETAIL)

        prompt = prompt.replace(CLIPBOARD_PLACEHOLDER, clipboard)
        status, detail = self._chat_completions(base_url, model, api_key, prompt)
        return ActionResult(status, "ai_text", detail, 0)

    def _read_clipboard(self) -> str | None:
        """Read the X11 clipboard with a fixed argv and no shell; None on failure."""
        try:
            completed = subprocess.run(
                CLIPBOARD_ARGV,
                capture_output=True,
                timeout=CLIPBOARD_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.decode("utf-8", errors="replace").strip()

    def _chat_completions(
        self, base_url: str, model: str, api_key: str, prompt: str
    ) -> tuple[ActionStatus, str]:
        """POST one chat completion; returns (status, detail or summary)."""
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        url = base_url.rstrip("/") + "/chat/completions"
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                raw = response.read()
        except urllib.error.HTTPError:
            return ActionStatus.ERROR, REQUEST_FAILED_DETAIL
        except TimeoutError:
            return ActionStatus.ERROR, REQUEST_TIMEOUT_DETAIL
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                return ActionStatus.ERROR, REQUEST_TIMEOUT_DETAIL
            return ActionStatus.ERROR, REQUEST_FAILED_DETAIL
        except OSError:
            return ActionStatus.ERROR, REQUEST_FAILED_DETAIL
        summary = self._parse_summary(raw)
        if summary is None:
            return ActionStatus.ERROR, MALFORMED_DETAIL
        return ActionStatus.OK, summary

    def _parse_summary(self, raw: bytes) -> str | None:
        """Extract the first line (truncated) of the completion text; None if malformed."""
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        choice = choices[0]
        if not isinstance(choice, dict):
            return None
        message = choice.get("message")
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        first_line = content.strip().splitlines()[0]
        return first_line[:MAX_DETAIL_CHARS]

    def _error(self, detail: str) -> ActionResult:
        return ActionResult(ActionStatus.ERROR, "ai_text", detail, 0)


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_env_name(name: str) -> bool:
    return _ENV_NAME_RE.fullmatch(name) is not None
