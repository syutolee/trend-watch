from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from trend_watch.utils.logging import LoggerMixin


def content_key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", errors="ignore"))
        h.update(b"\x00")
    return h.hexdigest()[:24]


class LLMCache(LoggerMixin):
    """On-disk JSON cache keyed by content hash. Re-runs are free."""

    def __init__(self, cache_dir: Path, namespace: str) -> None:
        self._path = cache_dir / f"{namespace}.json"
        self._data: dict[str, Any] = {}
        self._dirty = False
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                self.log.warning("Cannot read cache %s: %s", self._path, exc)
                self._data = {}

    def get(self, key: str) -> Any | None:
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._dirty = True

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def flush(self) -> None:
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False), encoding="utf-8"
        )
        self._dirty = False
        self.log.info("LLM cache flushed: %d entries → %s", len(self._data), self._path)
