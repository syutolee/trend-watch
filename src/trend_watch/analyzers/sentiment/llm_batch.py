"""Local-LLM batch sentiment — fills the gap left by push/boo-only analysis.

Generic crawler articles have no push/boo signal, so PNRatioAnalyzer returns
neutral 0.0 for all of them. This analyzer sends those posts to a local LLM
(gemma4:e4b via Ollama) in batches and returns a real sentiment score per post
at $0 API cost.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from trend_watch.llm.cache import LLMCache, content_key
from trend_watch.llm.client import LLMClient
from trend_watch.models import NormalizedDocument
from trend_watch.utils.logging import LoggerMixin

_CONTENT_LIMIT = 280
_DEFAULT_BATCH = 8

_SYSTEM = """\
You are a sentiment analysis assistant. Determine the overall sentiment of each post's author
toward the product, service, or topic discussed.
Rules:
1. Consider sarcasm and indirect negative expressions
2. Focus on the author's stance, not neutral descriptions
3. Output ONLY a JSON array, no explanation or markdown
"""

_USER_TEMPLATE = """\
Classify the sentiment of each post below. Return a JSON array.
sentiment must be one of: positive / negative / neutral
score is a float from -1.0 (most negative) to 1.0 (most positive)

Format (strict, one object per post):
[{{"id":"<id>","sentiment":"negative","score":-0.6}}, ...]

Posts:
{posts}"""


@dataclass
class LLMBatchSentimentReport:
    scores: dict[str, float] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    processed: int = 0
    cached_hits: int = 0
    errors: int = 0


class LLMBatchSentimentAnalyzer(LoggerMixin):

    def __init__(
        self,
        client: LLMClient | None = None,
        cache_dir: Path = Path("data-watch/llm-cache"),
        batch_size: int = _DEFAULT_BATCH,
    ) -> None:
        self._client = client or LLMClient(think=False)
        self._cache = LLMCache(cache_dir, namespace="sentiment")
        self._batch = max(1, batch_size)

    def analyze(
        self,
        docs: list[NormalizedDocument],
        *,
        max_docs: int | None = None,
    ) -> LLMBatchSentimentReport:
        report = LLMBatchSentimentReport()
        targets = docs[:max_docs] if max_docs else docs

        pending: list[tuple[str, str]] = []
        for doc in targets:
            text = (doc.post.title + "。" + doc.post.content)[:_CONTENT_LIMIT].strip()
            if not text:
                continue
            ckey = content_key(text)
            hit = self._cache.get(ckey)
            if hit is not None:
                report.scores[doc.post.id] = hit["score"]
                report.labels[doc.post.id] = hit["sentiment"]
                report.cached_hits += 1
            else:
                pending.append((doc.post.id, text))

        self.log.info(
            "LLM sentiment: %d targets, %d cached, %d to call (%s, batch=%d)",
            len(targets), report.cached_hits, len(pending), self._client.provider, self._batch,
        )

        for i in range(0, len(pending), self._batch):
            chunk = pending[i : i + self._batch]
            self._process_chunk(chunk, report)

        self._cache.flush()
        self.log.info(
            "LLM sentiment done: %d processed, %d cached, %d errors",
            report.processed, report.cached_hits, report.errors,
        )
        return report

    def _process_chunk(
        self, chunk: list[tuple[str, str]], report: LLMBatchSentimentReport
    ) -> None:
        posts_block = "\n".join(
            f'{{"id":"{pid}"}} {text}' for pid, text in chunk
        )
        user = _USER_TEMPLATE.format(posts=posts_block)
        try:
            raw = self._client.complete_text(_SYSTEM, user)
            parsed = self._parse_array(raw)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("LLM sentiment chunk failed: %s", exc)
            report.errors += len(chunk)
            return

        by_id = {str(o.get("id")): o for o in parsed if isinstance(o, dict)}
        for pid, text in chunk:
            obj = by_id.get(pid)
            if not obj:
                report.errors += 1
                continue
            label = str(obj.get("sentiment", "neutral")).lower()
            if label not in ("positive", "negative", "neutral"):
                label = "neutral"
            try:
                score = max(-1.0, min(1.0, float(obj.get("score", 0.0))))
            except (TypeError, ValueError):
                score = 0.0
            report.scores[pid] = round(score, 4)
            report.labels[pid] = label
            report.processed += 1
            self._cache.set(content_key(text), {"sentiment": label, "score": round(score, 4)})

    @staticmethod
    def _parse_array(raw: str) -> list:
        raw = raw.strip()
        if "</think>" in raw:
            raw = raw.split("</think>", 1)[1].strip()
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group())
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
