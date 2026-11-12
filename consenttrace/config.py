"""Runtime settings read from the environment (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env", *, model_var: str = "LLM_MODEL") -> LLMSettings | None:
        """Return settings, or None when no API key is configured (offline / replay mode)."""
        if env_file is not None:
            load_dotenv(env_file, override=False)
        api_key = os.environ.get("LLM_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
            model=os.environ.get(model_var, DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            api_key=api_key,
        )
