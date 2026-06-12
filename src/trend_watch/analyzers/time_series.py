from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from trend_watch.models import NormalizedDocument
from trend_watch.utils.logging import LoggerMixin


@dataclass
class TermTimeSeries:
    term: str
    freq: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def peak_period(self) -> str | None:
        if not self.counts:
            return None
        return max(self.counts, key=lambda k: self.counts[k])


@dataclass
class TimeSeriesReport:
    freq: str
    series: list[TermTimeSeries] = field(default_factory=list)
    volume: dict[str, int] = field(default_factory=dict)

    def get(self, term: str) -> TermTimeSeries | None:
        return next((s for s in self.series if s.term == term), None)


class TimeSeriesAnalyzer(LoggerMixin):

    def analyze(
        self,
        docs: list[NormalizedDocument],
        terms: list[str],
        freq: str = "W",
    ) -> TimeSeriesReport:
        if not docs:
            return TimeSeriesReport(freq=freq)

        rows: list[dict] = []
        for doc in docs:
            t = doc.post.post_time
            text = doc.post.title + " " + doc.post.content
            text += " " + " ".join(r.content for r in doc.reactions)
            rows.append({"time": t, "text": text})

        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time").sort_index()

        vol_series = df.resample(freq).size()
        volume = {str(k.date()): int(v) for k, v in vol_series.items()}

        ts_list: list[TermTimeSeries] = []
        for term in terms:
            df[f"_has_{term}"] = df["text"].str.contains(term, regex=False)
            term_counts = df[f"_has_{term}"].resample(freq).sum()
            counts = {str(k.date()): int(v) for k, v in term_counts.items() if v > 0}
            ts_list.append(TermTimeSeries(term=term, freq=freq, counts=counts))

        self.log.info(
            "Time series: %d terms × %d periods (%s)",
            len(terms), len(volume), freq,
        )
        return TimeSeriesReport(freq=freq, series=ts_list, volume=volume)
