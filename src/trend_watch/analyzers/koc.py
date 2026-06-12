from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from trend_watch.analyzers.entity.extractor import EntityExtractor
from trend_watch.analyzers.kol import KOLProfile, KOLReport
from trend_watch.models import NormalizedDocument
from trend_watch.utils.logging import LoggerMixin

_ANONYMOUS_IDS: frozenset[str] = frozenset({"", "匿名", "anonymous", "Anonymous", "unknown", " "})
_MAX_USER_ID_LEN = 40


def _is_genuine_user(user_id: str) -> bool:
    uid = user_id.strip()
    if not uid or uid in _ANONYMOUS_IDS:
        return False
    if len(uid) > _MAX_USER_ID_LEN:
        return False
    return True


_PERSONA_LABELS: dict[str, str] = {
    "brand_advocate": "Brand Advocate",
    "product_reviewer": "Product Reviewer",
    "concern_raiser": "Concern Raiser",
    "community_helper": "Community Helper",
}
_SENTIMENT_LABELS: dict[str, str] = {
    "positive": "Mostly Positive",
    "negative": "Mostly Negative",
    "mixed": "Mixed",
    "unknown": "Neutral",
}


@dataclass
class KOCProfile:
    user_id: str
    post_count: int
    received_reactions: int
    influence_score: float
    sentiment_bias: str
    top_entities: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    persona_type: str = "community_helper"
    koc_tier: str = "engaged_participant"
    koc_reason: str = ""


@dataclass
class KOCReport:
    profiles: list[KOCProfile] = field(default_factory=list)

    def top_koc(self, n: int = 12) -> list[KOCProfile]:
        return sorted(self.profiles, key=lambda p: p.influence_score, reverse=True)[:n]


class KOCAnalyzer(LoggerMixin):

    def __init__(self, dict_dir: Path | None = None) -> None:
        self._dict_dir = dict_dir or Path("data/dictionaries")

    def analyze(
        self,
        docs: list[NormalizedDocument],
        kol_report: KOLReport,
        anomaly_report=None,
    ) -> KOCReport:
        suspicious_authors: set[str] = set()
        if anomaly_report:
            suspicious_post_ids = {f.post_id for f in anomaly_report.suspicious_posts}
            for doc in docs:
                if doc.post.id in suspicious_post_ids:
                    suspicious_authors.add(doc.post.author)

        user_docs: dict[str, list[NormalizedDocument]] = defaultdict(list)
        for doc in docs:
            if doc.post.author not in suspicious_authors:
                user_docs[doc.post.author].append(doc)

        extractor: EntityExtractor | None = None
        try:
            if self._dict_dir.exists():
                extractor = EntityExtractor.from_dir(self._dict_dir)
        except Exception:
            self.log.warning("KOCAnalyzer: entity extractor unavailable, skipping topic affinity")

        kol_by_id = {p.user_id: p for p in kol_report.profiles}

        profiles: list[KOCProfile] = []
        for user_id, user_doc_list in user_docs.items():
            if not _is_genuine_user(user_id):
                continue
            kol = kol_by_id.get(user_id)
            if kol is None or kol.post_count < 2:
                continue

            top_entities: dict[str, list[tuple[str, int]]] = {}
            if extractor is not None:
                top_entities = self._extract_user_entities(extractor, user_doc_list)

            persona = self._classify_persona(kol, top_entities)
            tier = self._assign_tier(kol)
            reason = self._build_reason(kol, top_entities, persona)

            profiles.append(KOCProfile(
                user_id=user_id,
                post_count=kol.post_count,
                received_reactions=kol.received_reactions,
                influence_score=kol.influence_score,
                sentiment_bias=kol.sentiment_bias,
                top_entities=top_entities,
                persona_type=persona,
                koc_tier=tier,
                koc_reason=reason,
            ))

        report = KOCReport(
            profiles=sorted(profiles, key=lambda p: p.influence_score, reverse=True)
        )
        self.log.info("KOC: %d profiles built", len(profiles))
        return report

    def _extract_user_entities(
        self,
        extractor: EntityExtractor,
        user_docs: list[NormalizedDocument],
    ) -> dict[str, list[tuple[str, int]]]:
        entity_report = extractor.analyze(user_docs)
        cats_present: set[str] = {
            m.category for post in entity_report.posts for m in post.mentions
        }
        result: dict[str, list[tuple[str, int]]] = {}
        for category in sorted(cats_present):
            top = entity_report.top_terms(category, 5)
            if top:
                result[category] = top
        return result

    def _classify_persona(self, kol: KOLProfile, top_entities: dict) -> str:
        category_counts = {
            cat: sum(count for _, count in terms)
            for cat, terms in top_entities.items()
        }
        if not category_counts:
            total = kol.positive_given + kol.negative_given + kol.neutral_given
            if total > kol.post_count * 5:
                return "community_helper"
            return "concern_raiser" if kol.sentiment_bias == "negative" else "product_reviewer"

        dominant_cat = max(category_counts, key=lambda c: category_counts[c])
        if dominant_cat == "concerns" or kol.sentiment_bias == "negative":
            return "concern_raiser"
        if dominant_cat == "brands" and kol.sentiment_bias == "positive":
            return "brand_advocate"
        if dominant_cat == "products":
            return "product_reviewer"
        return "brand_advocate"

    def _assign_tier(self, kol: KOLProfile) -> str:
        if kol.influence_score >= 0.5:
            return "core_consumer"
        if kol.influence_score >= 0.15:
            return "active_reviewer"
        return "engaged_participant"

    def _build_reason(self, kol: KOLProfile, top_entities: dict, persona: str) -> str:
        all_mentions: list[tuple[str, int]] = [
            item for terms in top_entities.values() for item in terms
        ]
        all_mentions.sort(key=lambda x: x[1], reverse=True)
        top_items = [t for t, _ in all_mentions[:3]]

        parts = [f"{kol.post_count} posts, {kol.received_reactions} reactions received"]
        if top_items:
            parts.append(f"Discusses: {', '.join(top_items)}")
        parts.append(f"Sentiment: {_SENTIMENT_LABELS.get(kol.sentiment_bias, 'Neutral')}")
        parts.append(f"Type: {_PERSONA_LABELS.get(persona, persona)}")
        return "; ".join(parts) + "."
