from __future__ import annotations

from dataclasses import dataclass, field

from trend_watch.models import Attitude, NormalizedDocument


@dataclass
class PostSentiment:
    post_id: str
    title: str
    push: int
    boo: int
    arrow: int
    pn_score: float
    sentiment: str  # "positive" | "negative" | "neutral" | "controversial"


@dataclass
class SentimentReport:
    posts: list[PostSentiment] = field(default_factory=list)

    @property
    def positive_count(self) -> int:
        return sum(1 for p in self.posts if p.sentiment == "positive")

    @property
    def negative_count(self) -> int:
        return sum(1 for p in self.posts if p.sentiment == "negative")

    @property
    def neutral_count(self) -> int:
        return sum(1 for p in self.posts if p.sentiment == "neutral")

    @property
    def controversial_count(self) -> int:
        return sum(1 for p in self.posts if p.sentiment == "controversial")

    @property
    def avg_pn_score(self) -> float:
        if not self.posts:
            return 0.0
        return sum(p.pn_score for p in self.posts) / len(self.posts)

    def top_positive(self, n: int = 5) -> list[PostSentiment]:
        return sorted(self.posts, key=lambda p: p.pn_score, reverse=True)[:n]

    def top_negative(self, n: int = 5) -> list[PostSentiment]:
        return sorted(self.posts, key=lambda p: p.pn_score)[:n]


def _classify(push: int, boo: int, arrow: int) -> tuple[float, str]:
    total = push + boo + arrow
    if total == 0:
        return 0.0, "neutral"

    score = (push - boo) / total

    if push >= 10 and boo >= 10 and boo / (push + 1e-9) > 0.4:
        return score, "controversial"
    if score > 0.2:
        return score, "positive"
    if score < -0.2:
        return score, "negative"
    return score, "neutral"


class PNRatioAnalyzer:

    def analyze(self, docs: list[NormalizedDocument]) -> SentimentReport:
        results: list[PostSentiment] = []
        for doc in docs:
            p = doc.post
            push = p.engagement.get("push", 0)
            boo = p.engagement.get("boo", 0)
            arrow = p.engagement.get("arrow", 0)

            if doc.reactions:
                push = sum(1 for r in doc.reactions if r.attitude == Attitude.POSITIVE)
                boo = sum(1 for r in doc.reactions if r.attitude == Attitude.NEGATIVE)
                arrow = sum(1 for r in doc.reactions if r.attitude == Attitude.NEUTRAL)

            score, label = _classify(push, boo, arrow)
            results.append(PostSentiment(
                post_id=p.id,
                title=p.title,
                push=push,
                boo=boo,
                arrow=arrow,
                pn_score=round(score, 4),
                sentiment=label,
            ))

        return SentimentReport(posts=results)
