from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from trend_watch.models import NormalizedDocument
from trend_watch.utils.logging import LoggerMixin


def _default_serializer(obj: object) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)  # type: ignore[arg-type]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    raise TypeError(type(obj))


class FileStorage(LoggerMixin):

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        base_dir.mkdir(parents=True, exist_ok=True)

    def save_normalized(self, docs: list[NormalizedDocument], board: str, platform: str = "watch") -> Path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = self.base_dir / f"{platform}_{board}_{ts}.json"
        data = [d.model_dump(mode="json") for d in docs]
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=_default_serializer),
            encoding="utf-8",
        )
        self.log.info("Saved %d normalized docs → %s", len(docs), path)
        return path

    def load_normalized(self, path: Path) -> list[NormalizedDocument]:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [NormalizedDocument.model_validate(d) for d in data]


class AnalysisStorage(LoggerMixin):

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, result: object, board: str) -> Path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = self.base_dir / f"watch_{board}_{ts}_analysis.json"

        payload: dict[str, Any] = {}
        for field in ("sentiment", "entities", "time_series", "anomaly", "kol", "topics", "keywords"):
            val = getattr(result, field, None)
            if val is not None:
                try:
                    payload[field] = asdict(val)  # type: ignore[arg-type]
                except Exception:
                    pass

        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_default_serializer),
            encoding="utf-8",
        )
        self.log.info("Saved analysis → %s", path)
        return path


class WatchStorage(LoggerMixin):
    """Convenience wrapper for the watch workflow — raw, analyzed, and report paths."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._raw = FileStorage(root / "raw")
        self._analysis = AnalysisStorage(root / "analyzed")
        (root / "reports").mkdir(parents=True, exist_ok=True)
        self._ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    def save_raw(self, docs: list[NormalizedDocument], board: str) -> Path:
        return self._raw.save_normalized(docs, board=board, platform="watch")

    def save_analysis(self, result: object, board: str) -> Path:
        return self._analysis.save(result, board=board)

    def report_path(self, board: str) -> Path:
        return self.root / "reports" / f"watch_{board}_{self._ts}_report.html"
