from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trend_watch.analyzers.anomaly import AnomalyDetector, AnomalyReport
from trend_watch.analyzers.entity.extractor import EntityExtractor, EntityReport
from trend_watch.analyzers.koc import KOCAnalyzer, KOCReport
from trend_watch.analyzers.kol import KOLIdentifier, KOLReport
from trend_watch.analyzers.sentiment.pn_ratio import PNRatioAnalyzer, SentimentReport
from trend_watch.analyzers.topic.clustering import ClusteringReport, TopicClusterer
from trend_watch.analyzers.topic.wordcloud import KeywordExtractor, WordCloudData
from trend_watch.analyzers.time_series import TimeSeriesAnalyzer, TimeSeriesReport
from trend_watch.models import Attitude, NormalizedDocument
from trend_watch.utils.logging import LoggerMixin
from trend_watch.utils.text import strip_boilerplate


@dataclass
class AnalysisResult:
    sentiment: SentimentReport | None = None
    entities: EntityReport | None = None
    time_series: TimeSeriesReport | None = None
    anomaly: AnomalyReport | None = None
    kol: KOLReport | None = None
    koc: KOCReport | None = None
    topics: ClusteringReport | None = None
    keywords: WordCloudData | None = None
    llm_sentiment: object | None = None


class AnalysisPipeline(LoggerMixin):

    def __init__(
        self,
        dict_dir: Path | None = None,
        *,
        ts_terms: list[str] | None = None,
        ts_freq: str = "W",
        n_clusters: int | None = None,
        use_local_llm: bool = False,
        llm_sample: int | None = None,
        extra_terms: dict[str, list[str]] | None = None,
    ) -> None:
        from trend_watch.config.settings import get_settings
        cfg = get_settings()
        self._dict_dir = dict_dir or cfg.dictionary_dir
        self._ts_terms = ts_terms
        self._ts_freq = ts_freq
        self._n_clusters = n_clusters
        self._use_local_llm = use_local_llm
        self._llm_sample = llm_sample
        self._extra_terms = extra_terms

    def run(self, docs: list[NormalizedDocument]) -> AnalysisResult:
        result = AnalysisResult()
        if not docs:
            return result

        # Preprocessing: strip boilerplate from content
        cleaned = 0
        for doc in docs:
            stripped = strip_boilerplate(doc.post.content)
            if stripped != doc.post.content:
                doc.post.content = stripped
                cleaned += 1
        if cleaned:
            self.log.info("Preprocess: stripped boilerplate from %d/%d posts", cleaned, len(docs))

        self.log.info("1/7  PN-ratio sentiment…")
        result.sentiment = PNRatioAnalyzer().analyze(docs)

        # Overlay local-LLM sentiment onto posts with no push/boo signal
        if self._use_local_llm and result.sentiment:
            self._overlay_llm_sentiment(docs, result)

        self.log.info("2/7  Entity extraction…")
        extractor = EntityExtractor.from_dir(self._dict_dir, extra_terms=self._extra_terms)
        result.entities = extractor.analyze(docs)

        self.log.info("3/7  Time-series volume…")
        terms = self._ts_terms or self._pick_top_terms(result.entities)
        result.time_series = TimeSeriesAnalyzer().analyze(docs, terms=terms, freq=self._ts_freq)

        self.log.info("4/7  Anomaly detection…")
        result.anomaly = AnomalyDetector().analyze(docs)

        self.log.info("5/7  KOL identification…")
        result.kol = KOLIdentifier().analyze(docs)

        self.log.info("5.5/7  KOC profiling…")
        result.koc = KOCAnalyzer(self._dict_dir).analyze(docs, result.kol, result.anomaly)

        self.log.info("6/7  Topic clustering + keywords…")
        result.topics = TopicClusterer(n_clusters=self._n_clusters).analyze(docs)
        result.keywords = KeywordExtractor().extract(docs)

        self._log_summary(result)
        return result

    def _overlay_llm_sentiment(
        self, docs: list[NormalizedDocument], result: AnalysisResult
    ) -> None:
        from trend_watch.analyzers.sentiment.llm_batch import LLMBatchSentimentAnalyzer

        # Only target posts with no push/boo signal and no non-neutral reactions
        blind = [
            doc for doc in docs
            if (doc.post.engagement.get("push", 0)
                + doc.post.engagement.get("boo", 0)
                + doc.post.engagement.get("arrow", 0) == 0)
            and not any(r.attitude != Attitude.NEUTRAL for r in doc.reactions)
        ]
        if not blind:
            self.log.info("LLM sentiment overlay: no push/boo-less posts, skipping")
            return

        self.log.info(
            "1.5/7  LLM sentiment overlay on %d posts (sample=%s)…",
            len(blind), self._llm_sample,
        )
        report = LLMBatchSentimentAnalyzer().analyze(blind, max_docs=self._llm_sample)

        overlaid = 0
        for ps in result.sentiment.posts:
            if ps.post_id in report.scores:
                ps.pn_score = report.scores[ps.post_id]
                ps.sentiment = report.labels.get(ps.post_id, ps.sentiment)
                overlaid += 1
        self.log.info("LLM sentiment overlay: updated %d posts", overlaid)

    def _pick_top_terms(self, entities: EntityReport) -> list[str]:
        cats_present: set[str] = {m.category for post in entities.posts for m in post.mentions}
        terms: list[str] = []
        for cat in sorted(cats_present):
            terms.extend(t for t, _ in entities.top_terms(cat, 3))
        return terms[:15]

    def _log_summary(self, r: AnalysisResult) -> None:
        if r.sentiment:
            self.log.info(
                "Sentiment: +%d -%d ~%d !%d  avg=%.3f",
                r.sentiment.positive_count,
                r.sentiment.negative_count,
                r.sentiment.neutral_count,
                r.sentiment.controversial_count,
                r.sentiment.avg_pn_score,
            )
        if r.anomaly:
            self.log.info("Anomaly: %d suspicious posts", r.anomaly.suspicious_count)
        if r.topics:
            self.log.info(
                "Topics: %d clusters, silhouette=%.3f",
                r.topics.n_clusters, r.topics.silhouette,
            )
        if r.kol:
            top = r.kol.top_by_influence(3)
            self.log.info("Top KOLs: %s", [p.user_id for p in top])
