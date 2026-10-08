"""Small, dependency-free configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path


_default_app_dir = Path.home() / ".pymol-flow"

APP_DIR = Path(
    os.environ.get("PYMOL_FLOW_WORKDIR")
    or _default_app_dir
).expanduser()
CAPTURE_DIR = APP_DIR / "captures"
DOWNLOAD_DIR = APP_DIR / "downloads"
DEFAULT_MODEL = "kimi-k2.7-code"
DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
DEFAULT_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"


def ensure_app_dirs() -> None:
    APP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    CAPTURE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def load_local_env() -> None:
    """Load a nearby .env without requiring python-dotenv.

    Existing non-empty environment variables always win. Only simple KEY=VALUE lines
    are accepted; this intentionally does not evaluate shell syntax.
    """
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
        Path.home() / ".pymol-flow" / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except Exception:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if " #" in value:
                value = value.split(" #", 1)[0]
            value = value.strip().strip("'\"")
            if key.replace("_", "").isalnum() and value:
                if not os.environ.get(key):
                    os.environ[key] = value
        return


def api_key() -> str:
    """Prefer the key saved through the app over development configuration."""
    load_local_env()
    from .keychain import read_api_key

    stored_key = read_api_key().strip()
    if stored_key:
        return stored_key
    return (
        os.environ.get("MOONSHOT_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
        or ""
    ).strip()


def normalize_model_name(raw_name: str) -> str:
    """Normalize user-friendly model names (e.g. 'Kimi K2.7 Code') to official API model IDs."""
    s = raw_name.strip()
    clean = s.lower().replace(" ", "").replace("_", "-")
    if "kimik2.7" in clean or "kimi-k2.7" in clean:
        return "kimi-k2.7-code"
    if "kimik3" in clean or "kimi-k3" in clean:
        return "kimi-k3"
    if "kimik2.6" in clean or "kimi-k2.6" in clean:
        return "kimi-k2.6"
    return s


def base_url() -> str:
    load_local_env()
    configured = (
        os.environ.get("MOONSHOT_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("DASHSCOPE_BASE_URL")
        or ""
    ).strip()
    curr_model = model().lower()
    # If model is Moonshot Kimi but base_url still points to old Qianwen/DashScope, auto-resolve to Moonshot base URL
    if "kimi" in curr_model and ("qianwen" in configured.lower() or "dashscope" in configured.lower()):
        return DEFAULT_BASE_URL
    return configured or DEFAULT_BASE_URL


def model() -> str:
    load_local_env()
    raw = (
        os.environ.get("MOONSHOT_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or os.environ.get("DASHSCOPE_MODEL")
        or DEFAULT_MODEL
    ).strip()
    return normalize_model_name(raw)


def transcription_model() -> str:
    return os.environ.get("OPENAI_TRANSCRIBE_MODEL", DEFAULT_TRANSCRIBE_MODEL).strip()


def thinking_mode() -> str:
    """Return the configured thinking mode: 'off' (default fast mode, sub-2s execution), 'auto', or 'on'."""
    load_local_env()
    val = (
        os.environ.get("MOONSHOT_ENABLE_THINKING")
        or os.environ.get("DASHSCOPE_ENABLE_THINKING")
        or "off"
    ).lower().strip()
    if val in {"true", "1", "yes", "on", "always"}:
        return "on"
    if val in {"auto"}:
        return "auto"
    return "off"


def enable_thinking() -> bool:
    return thinking_mode() == "on"


def thinking_budget() -> int:
    """Return max thinking tokens (budget). Default is 1024 to prevent runaway 70+ second thinking loops."""
    load_local_env()
    val = (
        os.environ.get("MOONSHOT_THINKING_BUDGET")
        or os.environ.get("DASHSCOPE_THINKING_BUDGET")
        or "1024"
    ).strip()
    try:
        return max(128, min(8192, int(val)))
    except ValueError:
        return 1024


def max_tokens() -> int:
    """Return max completion tokens to prevent runaway output token consumption."""
    load_local_env()
    val = (
        os.environ.get("MOONSHOT_MAX_TOKENS")
        or os.environ.get("OPENAI_MAX_TOKENS")
        or os.environ.get("DASHSCOPE_MAX_TOKENS")
        or "2048"
    ).strip()
    try:
        return max(256, min(8192, int(val)))
    except ValueError:
        return 2048


def max_history_messages() -> int:
    """Return maximum number of historical messages retained in agent context."""
    load_local_env()
    val = os.environ.get("PYMOL_FLOW_MAX_HISTORY", "20").strip()
    try:
        return max(6, min(100, int(val)))
    except ValueError:
        return 20


def max_tool_output_chars() -> int:
    """Return maximum characters per tool execution output to prevent context explosion."""
    load_local_env()
    val = os.environ.get("PYMOL_FLOW_MAX_TOOL_OUTPUT", "1200").strip()
    try:
        return max(200, min(10000, int(val)))
    except ValueError:
        return 1200


def max_scene_objects() -> int:
    """Return maximum objects and selections inspected in scene summary."""
    load_local_env()
    val = os.environ.get("PYMOL_FLOW_MAX_SCENE_OBJECTS", "20").strip()
    try:
        return max(5, min(100, int(val)))
    except ValueError:
        return 20
