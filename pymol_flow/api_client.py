"""Client for OpenAI and compatible endpoints (such as DashScope / Qwen)."""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .config import api_key as get_configured_api_key, base_url as get_configured_base_url


class APIError(RuntimeError):
    pass


class AttrDict(dict):
    """Dictionary with SDK-like attribute access for the agent loop."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _objects(value: Any) -> Any:
    if isinstance(value, dict):
        return AttrDict({key: _objects(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_objects(item) for item in value]
    return value


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8", "replace"))
        return payload.get("error", {}).get("message") or str(exc)
    except Exception:
        return str(exc)


class ChatCompletionsProxy:
    def __init__(self, client: OpenAIHTTPClient):
        self.client = client
        self.completions = self

    def create(self, **kwargs) -> Any:
        stream = kwargs.get("stream", False)
        path = "/chat/completions"

        # Unpack extra_body into top-level kwargs (compatible with OpenAI Python SDK convention)
        # so that providers like DashScope / Qwen receive enable_thinking, thinking_budget at top level.
        if "extra_body" in kwargs and isinstance(kwargs["extra_body"], dict):
            extra = kwargs.pop("extra_body")
            for k, v in extra.items():
                if k not in kwargs:
                    kwargs[k] = v

        body = json.dumps(kwargs, separators=(",", ":")).encode("utf-8")

        if stream:
            return self._stream_request(path, body)

        payload = self.client._request(path, body, "application/json")
        return _objects(payload)

    def _stream_request(self, path: str, body: bytes):
        request = urllib.request.Request(
            self.client.base_url + path,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.client.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "PyMOL-Flow/1.2.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.client.timeout) as response:
                for line in response:
                    line_str = line.decode("utf-8", "replace").strip()
                    if not line_str or line_str.startswith(":"):
                        continue
                    if line_str.startswith("data:"):
                        data_str = line_str[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            yield _objects(chunk)
                        except json.JSONDecodeError:
                            continue
        except urllib.error.HTTPError as exc:
            raise APIError(_error_message(exc)) from exc
        except urllib.error.URLError as exc:
            raise APIError(f"Connection error: {exc.reason}") from exc


class OpenAIHTTPClient:
    def __init__(self, api_key: str, base_url: str | None = None, timeout: int = 120):
        self.api_key = api_key
        self.base_url = (base_url or get_configured_base_url()).rstrip("/")
        self.timeout = timeout
        self.chat = ChatCompletionsProxy(self)
        self.responses = self

    def _request(self, path: str, body: bytes, content_type: str) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": content_type,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "PyMOL-Flow/1.2.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise APIError(_error_message(exc)) from exc
        except urllib.error.URLError as exc:
            raise APIError(f"Connection error: {exc.reason}") from exc

    def create(self, **kwargs) -> Any:
        """Fallback for legacy responses endpoint."""
        payload = self._request(
            "/responses",
            json.dumps(kwargs, separators=(",", ":")).encode("utf-8"),
            "application/json",
        )
        output_text = []
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text.append(content.get("text", ""))
        payload["output_text"] = "\n".join(output_text)
        return _objects(payload)

    def transcribe(self, path: Path, model: str) -> str:
        boundary = "----PyMOLChat" + uuid.uuid4().hex
        filename = path.name
        mime = mimetypes.guess_type(filename)[0] or "audio/wav"
        chunks = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{model}\r\n".encode(),
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n"
            ).encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        payload = self._request(
            "/audio/transcriptions",
            b"".join(chunks),
            f"multipart/form-data; boundary={boundary}",
        )
        return str(payload.get("text", "")).strip()


def get_client(api_key: str | None = None, base_url: str | None = None) -> Any:
    """Return an OpenAI client configured for the selected endpoint with robust timeouts."""
    key = api_key or get_configured_api_key()
    url = base_url or get_configured_base_url()
    try:
        from openai import OpenAI
        import httpx

        timeout = httpx.Timeout(timeout=120.0, connect=30.0)
        return OpenAI(api_key=key, base_url=url, timeout=timeout, max_retries=3)
    except ImportError:
        return OpenAIHTTPClient(api_key=key, base_url=url)
