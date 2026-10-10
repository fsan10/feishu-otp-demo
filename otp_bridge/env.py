"""Load the project's small, non-executable .env format."""

from __future__ import annotations

import os
import re
from pathlib import Path


_ALLOWED_KEYS = {
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_SMS_WEBHOOK_URL",
    "FEISHU_SMS_WEBHOOK_SECRET",
}
_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path: str | Path | None = None) -> bool:
    """Load supported KEY=VALUE entries from .env without overriding the process."""
    if path is None:
        candidates = (Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env")
        env_path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if env_path is None:
            return False
    else:
        env_path = Path(path)
        if not env_path.is_file():
            return False

    with env_path.open(encoding="utf-8-sig") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" not in line:
                raise ValueError(f"invalid .env syntax on line {line_number}")

            key, raw_value = line.split("=", 1)
            key = key.strip()
            value = raw_value.strip()
            if not _KEY_PATTERN.fullmatch(key) or key not in _ALLOWED_KEYS:
                raise ValueError(f"unsupported .env entry on line {line_number}")

            if value.startswith(("'", '"')):
                quote = value[0]
                if len(value) < 2 or value[-1] != quote:
                    raise ValueError(f"invalid .env quoting on line {line_number}")
                value = value[1:-1]

            # Explicit environment variables (including managed secrets) take precedence.
            os.environ.setdefault(key, value)
    return True
