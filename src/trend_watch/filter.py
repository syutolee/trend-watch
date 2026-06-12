"""Keyword filtering and hit statistics for the `watch` workflow."""
from __future__ import annotations

from dataclasses import dataclass, field

from trend_watch.models import NormalizedDocument

WATCH_KEYWORD_CATEGORY = "watch_keywords"


@dataclass
class KeywordPostHit:
    post_id: str
    title: str
    url: str
    mention_count: int
    in_title: bool
    sentiment: str = "neutral"
    pn_score: float = 0.0


@dataclass
class KeywordHit:
    keyword: str
    n_posts: int
    total_mentions: int
    sentiment_counts: dict[str, int] = field(default_factory=dict)
    top_posts: list[KeywordPostHit] = field(default_factory=list)


def _count_in_doc(doc: NormalizedDocument, kw: str) -> int:
    kw_lower = kw.lower()
    corpus = (
        doc.post.title.lower()
        + " "
        + doc.post.content.lower()
        + " "
        + " ".join(r.content.lower() for r in doc.reactions)
    )
    return corpus.count(kw_lower)


def match_keywords(doc: NormalizedDocument, keywords: list[str]) -> dict[str, int]:
    """Return {keyword: count} for keywords with at least one match."""
    result: dict[str, int] = {}
    for kw in keywords:
        count = _count_in_doc(doc, kw)
        if count > 0:
            result[kw] = count
    return result


def filter_docs_by_keywords(
    docs: list[NormalizedDocument], keywords: list[str]
) -> list[NormalizedDocument]:
    """Keep only docs that mention at least one keyword (OR logic)."""
    kws_lower = [k.lower() for k in keywords]
    kept = []
    for doc in docs:
        corpus = (
            doc.post.title.lower()
            + " "
            + doc.post.content.lower()
            + " "
            + " ".join(r.content.lower() for r in doc.reactions)
        )
        if any(kw in corpus for kw in kws_lower):
            kept.append(doc)
    return kept


def build_keyword_hits(
    docs: list[NormalizedDocument],
    keywords: list[str],
    sentiment: object | None,
    top_n: int = 5,
) -> list[KeywordHit]:
    """Build per-keyword hit statistics, back-filling sentiment from SentimentReport."""
    sent_map: dict[str, tuple[str, float]] = {}
    if sentiment is not None:
        for ps in getattr(sentiment, "posts", []):
            sent_map[ps.post_id] = (getattr(ps, "sentiment", "neutral"), getattr(ps, "pn_score", 0.0))

    hits: list[KeywordHit] = []
    for kw in keywords:
        kw_lower = kw.lower()
        post_hits: list[KeywordPostHit] = []

        for doc in docs:
            count = _count_in_doc(doc, kw)
            if count == 0:
                continue
            in_title = kw_lower in doc.post.title.lower()
            sent_label, pn_score = sent_map.get(doc.post.id, ("neutral", 0.0))
            post_hits.append(KeywordPostHit(
                post_id=doc.post.id,
                title=doc.post.title,
                url=doc.post.url,
                mention_count=count,
                in_title=in_title,
                sentiment=sent_label,
                pn_score=pn_score,
            ))

        post_hits.sort(key=lambda h: h.mention_count + (5 if h.in_title else 0), reverse=True)

        sentiment_counts: dict[str, int] = {"positive": 0, "negative": 0, "neutral": 0, "controversial": 0}
        for ph in post_hits:
            label = ph.sentiment if ph.sentiment in sentiment_counts else "neutral"
            sentiment_counts[label] += 1

        total_mentions = sum(ph.mention_count for ph in post_hits)
        hits.append(KeywordHit(
            keyword=kw,
            n_posts=len(post_hits),
            total_mentions=total_mentions,
            sentiment_counts=sentiment_counts,
            top_posts=post_hits[:top_n],
        ))

    return hits
