"""Production-independent EventPulse identity oracle."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def event_identity(value: dict[str, Any]) -> str:
    projected = {key: item for key, item in value.items() if key != "ingest_time_ms"}
    encoded = json.dumps(projected, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()
