from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trend_watch.models import Attitude, NormalizedDocument
from trend_watch.utils.logging import LoggerMixin

_DENSE_PUSH_WINDOW_MINUTES = 15
_DENSE_PUSH_COUNT = 5
_DENSE_PUSH_WEIGHT = 0.35
_SAME_USER_MAX_RATIO = 0.40
_MIN_POSITIVE_FOR_DOMINANCE = 10
_DOMINANCE_WEIGHT = 0.6
_DUPE_CONTENT_MIN_LEN = 10
_DUPE_MIN_COUNT = 3
_DUPE_WEIGHT = 0.6
_NIGHT_HOUR_START = 0
_NIGHT_HOUR_END = 5
_NIGHT_SURGE_MIN_COUNT = 10
_NIGHT_SURGE_WEIGHT = 0.3
_REPEAT_PUSHER_MIN_POSTS = 3
_REPEAT_PUSHER_WEIGHT = 0.4
_SUSPICIOUS_THRESHOLD = 0.55


@dataclass
class AnomalyFlag:
    post_id: str
    title: str
    flags: list[str] = field(default_factory=list)
    risk_score: float = 0.0

    @property
    def is_suspicious(self) -> bool:
        return self.risk_score >= _SUSPICIOUS_THRESHOLD


@dataclass
class AnomalyReport:
    flags: list[AnomalyFlag] = field(default_factory=list)

    @property
    def suspicious_posts(self) -> list[AnomalyFlag]:
        return [f for f in self.flags if f.is_suspicious]

    @property
    def suspicious_count(self) -> int:
        return len(self.suspicious_posts)


class AnomalyDetector(LoggerMixin):

    def analyze(self, docs: list[NormalizedDocument]) -> AnomalyReport:
        results: list[AnomalyFlag] = []
        dense_push_users: dict[str, list[str]] = defaultdict(list)

        for doc in docs:
            flag, dp_users = self._check_post(doc)
            results.append(flag)
            for user in dp_users:
                dense_push_users[user].append(doc.post.id)

        repeat_offenders: set[str] = {
            user for user, posts in dense_push_users.items()
            if len(posts) >= _REPEAT_PUSHER_MIN_POSTS
        }

        if repeat_offenders:
            post_id_to_flag = {f.post_id: f for f in results}
            for user in repeat_offenders:
                for post_id in dense_push_users[user]:
                    flag = post_id_to_flag.get(post_id)
                    if flag:
                        signal = f"repeat_pusher:{user}({len(dense_push_users[user])} posts)"
                        if signal not in flag.flags:
                            flag.flags.append(signal)
                            flag.risk_score = min(1.0, flag.risk_score + _REPEAT_PUSHER_WEIGHT)

        suspicious = sum(1 for f in results if f.is_suspicious)
        self.log.info("Anomaly scan: %d/%d posts suspicious", suspicious, len(results))
        return AnomalyReport(flags=results)

    def _check_post(self, doc: NormalizedDocument) -> tuple[AnomalyFlag, list[str]]:
        post = doc.post
        reactions = doc.reactions
        flag = AnomalyFlag(post_id=post.id, title=post.title)
        signals: list[tuple[str, float]] = []
        dp_users: list[str] = []

        dense, users = self._check_dense_push(reactions)
        signals.extend(dense)
        dp_users.extend(users)
        signals.extend(self._check_single_user_dominance(reactions))
        signals.extend(self._check_duplicate_content(reactions))
        signals.extend(self._check_night_surge(reactions))

        if signals:
            flag.flags = [s for s, _ in signals]
            flag.risk_score = min(1.0, sum(w for _, w in signals))

        return flag, dp_users

    def _check_dense_push(self, reactions: list) -> tuple[list[tuple[str, float]], list[str]]:
        user_times: dict[str, list[datetime]] = defaultdict(list)
        for r in reactions:
            if r.reaction_time and r.attitude == Attitude.POSITIVE:
                user_times[r.author].append(r.reaction_time)

        findings: list[tuple[str, float]] = []
        flagged_users: list[str] = []

        for user, times in user_times.items():
            times_sorted = sorted(times)
            for i in range(len(times_sorted) - _DENSE_PUSH_COUNT + 1):
                window_end = times_sorted[i] + timedelta(minutes=_DENSE_PUSH_WINDOW_MINUTES)
                burst = [t for t in times_sorted[i:] if t <= window_end]
                if len(burst) >= _DENSE_PUSH_COUNT:
                    findings.append((
                        f"dense_push:{user}({len(burst)} in {_DENSE_PUSH_WINDOW_MINUTES}min)",
                        _DENSE_PUSH_WEIGHT,
                    ))
                    flagged_users.append(user)
                    break

        return findings, flagged_users

    def _check_single_user_dominance(self, reactions: list) -> list[tuple[str, float]]:
        positive = [r for r in reactions if r.attitude == Attitude.POSITIVE]
        if len(positive) < _MIN_POSITIVE_FOR_DOMINANCE:
            return []
        counts = Counter(r.author for r in positive)
        top_user, top_count = counts.most_common(1)[0]
        ratio = top_count / len(positive)
        if ratio > _SAME_USER_MAX_RATIO:
            return [(f"dominant_pusher:{top_user}({ratio:.0%})", _DOMINANCE_WEIGHT)]
        return []

    def _check_duplicate_content(self, reactions: list) -> list[tuple[str, float]]:
        texts = [
            r.content.strip()
            for r in reactions
            if len(r.content.strip()) >= _DUPE_CONTENT_MIN_LEN
        ]
        counts = Counter(texts)
        dupes = [(t, c) for t, c in counts.items() if c >= _DUPE_MIN_COUNT]
        if dupes:
            return [(f"duplicate_content({len(dupes)} types)", _DUPE_WEIGHT)]
        return []

    def _check_night_surge(self, reactions: list) -> list[tuple[str, float]]:
        night_positive = [
            r for r in reactions
            if r.attitude == Attitude.POSITIVE
            and r.reaction_time
            and _NIGHT_HOUR_START <= r.reaction_time.hour <= _NIGHT_HOUR_END
        ]
        if len(night_positive) >= _NIGHT_SURGE_MIN_COUNT:
            return [(f"night_surge({len(night_positive)} positive reactions at night)", _NIGHT_SURGE_WEIGHT)]
        return []
