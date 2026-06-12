from __future__ import annotations

from pathlib import Path

import jieba

from trend_watch.utils.logging import LoggerMixin


class DictionaryManager(LoggerMixin):
    """Loads domain word lists from *.txt files and registers them with jieba.

    Category names are derived from the filename stems so any domain is supported.
    """

    def __init__(self, dict_dir: Path) -> None:
        self.dict_dir = dict_dir
        self._terms: dict[str, list[str]] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return

        jieba.setLogLevel("WARNING")
        txt_files = sorted(self.dict_dir.glob("*.txt")) if self.dict_dir.exists() else []
        if not txt_files:
            self.log.warning("No .txt dictionary files found in %s", self.dict_dir)

        for path in txt_files:
            category = path.stem
            terms = [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            ]
            for term in terms:
                jieba.add_word(term, freq=1000)
            self._terms[category] = terms
            self.log.info("Loaded %d %s terms", len(terms), category)

        self._loaded = True

    def terms(self, category: str) -> list[str]:
        if not self._loaded:
            self.load()
        return self._terms.get(category, [])

    def add_terms(self, category: str, terms: list[str]) -> None:
        """Inject an in-memory term list (not persisted to disk) and register with jieba."""
        if not self._loaded:
            self.load()
        existing = set(self._terms.get(category, []))
        new_terms = [t for t in terms if t not in existing]
        for t in new_terms:
            jieba.add_word(t, freq=1000)
        self._terms.setdefault(category, []).extend(new_terms)

    def all_terms(self) -> dict[str, list[str]]:
        if not self._loaded:
            self.load()
        return dict(self._terms)
