from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from trend_watch.analyzers.entity.dictionary import DictionaryManager
from trend_watch.models import NormalizedDocument
from trend_watch.utils.logging import LoggerMixin


@dataclass
class EntityMention:
    term: str
    category: str
    count: int
    in_title: bool
    in_reactions: int


@dataclass
class PostEntities:
    post_id: str
    title: str
    mentions: list[EntityMention] = field(default_factory=list)


@dataclass
class EntityReport:
    posts: list[PostEntities] = field(default_factory=list)

    def top_terms(self, category: str, n: int = 10) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for post in self.posts:
            for m in post.mentions:
                if m.category == category:
                    counts[m.term] = counts.get(m.term, 0) + m.count
        return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:n]


class EntityExtractor(LoggerMixin):

    def __init__(self, dict_manager: DictionaryManager) -> None:
        self._dm = dict_manager

    @classmethod
    def from_dir(
        cls,
        dict_dir: Path,
        extra_terms: dict[str, list[str]] | None = None,
    ) -> EntityExtractor:
        dm = DictionaryManager(dict_dir)
        dm.load()
        if extra_terms:
            for category, terms in extra_terms.items():
                dm.add_terms(category, terms)
        return cls(dm)

    def analyze(self, docs: list[NormalizedDocument]) -> EntityReport:
        return EntityReport(posts=[self._extract_post(doc) for doc in docs])

    def _extract_post(self, doc: NormalizedDocument) -> PostEntities:
        post = doc.post
        all_terms = self._dm.all_terms()

        title_text = post.title + " " + post.title_category
        body_text = post.content
        reaction_texts = [r.content for r in doc.reactions]
        full_text = title_text + "\n" + body_text + "\n" + "\n".join(reaction_texts)

        mentions: list[EntityMention] = []
        for category, terms_list in all_terms.items():
            for term in terms_list:
                total = full_text.count(term)
                if total == 0:
                    continue
                in_title = term in title_text
                in_reactions = sum(1 for rt in reaction_texts if term in rt)
                mentions.append(EntityMention(
                    term=term,
                    category=category,
                    count=total,
                    in_title=in_title,
                    in_reactions=in_reactions,
                ))

        return PostEntities(post_id=post.id, title=post.title, mentions=mentions)
