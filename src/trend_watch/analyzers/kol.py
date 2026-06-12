from __future__ import annotations

from dataclasses import dataclass, field

from trend_watch.models import Attitude, NormalizedDocument
from trend_watch.utils.logging import LoggerMixin


@dataclass
class KOLProfile:
    user_id: str
    post_count: int = 0
    reaction_count: int = 0
    received_reactions: int = 0
    positive_given: int = 0
    negative_given: int = 0
    neutral_given: int = 0
    influence_score: float = 0.0

    @property
    def sentiment_bias(self) -> str:
        total = self.positive_given + self.negative_given + self.neutral_given
        if total == 0:
            return "unknown"
        if self.positive_given / total > 0.6:
            return "positive"
        if self.negative_given / total > 0.6:
            return "negative"
        return "mixed"


@dataclass
class KOLReport:
    profiles: list[KOLProfile] = field(default_factory=list)

    def top_by_influence(self, n: int = 10) -> list[KOLProfile]:
        return sorted(self.profiles, key=lambda p: p.influence_score, reverse=True)[:n]

    def top_authors(self, n: int = 10) -> list[KOLProfile]:
        return sorted(self.profiles, key=lambda p: p.post_count, reverse=True)[:n]


class KOLIdentifier(LoggerMixin):

    def analyze(self, docs: list[NormalizedDocument]) -> KOLReport:
        profiles: dict[str, KOLProfile] = {}

        def get(uid: str) -> KOLProfile:
            if uid not in profiles:
                profiles[uid] = KOLProfile(user_id=uid)
            return profiles[uid]

        for doc in docs:
            author = doc.post.author
            p = get(author)
            p.post_count += 1
            p.received_reactions += len(doc.reactions)

            for r in doc.reactions:
                rp = get(r.author)
                rp.reaction_count += 1
                if r.attitude == Attitude.POSITIVE:
                    rp.positive_given += 1
                elif r.attitude == Attitude.NEGATIVE:
                    rp.negative_given += 1
                else:
                    rp.neutral_given += 1

        max_posts = max((p.post_count for p in profiles.values()), default=1) or 1
        max_reactions = max((p.reaction_count for p in profiles.values()), default=1) or 1
        max_received = max((p.received_reactions for p in profiles.values()), default=1) or 1

        for p in profiles.values():
            p.influence_score = round(
                0.5 * (p.post_count / max_posts)
                + 0.2 * (p.reaction_count / max_reactions)
                + 0.3 * (p.received_reactions / max_received),
                4,
            )

        report = KOLReport(profiles=list(profiles.values()))
        self.log.info(
            "KOL: %d unique users, top influencer: %s (%.3f)",
            len(profiles),
            report.top_by_influence(1)[0].user_id if profiles else "—",
            report.top_by_influence(1)[0].influence_score if profiles else 0,
        )
        return report
