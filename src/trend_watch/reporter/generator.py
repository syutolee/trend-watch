from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from trend_watch.analyzers.pipeline import AnalysisResult
from trend_watch.models import NormalizedDocument
from trend_watch.reporter import charts
from trend_watch.utils.logging import LoggerMixin

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class HTMLReportGenerator(LoggerMixin):

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html"]),
        )

    def generate(
        self,
        docs: list[NormalizedDocument],
        result: AnalysisResult,
        output_path: Path,
        board: str = "",
        summary_text: str = "",
        embed_plotly: bool = False,
        keyword_hits: list | None = None,
        report_title: str | None = None,
    ) -> Path:
        ctx = self._build_context(
            docs, result, board, summary_text,
            keyword_hits=keyword_hits, report_title=report_title,
        )
        ctx["plotly_js_inline"] = _get_plotly_js() if embed_plotly else None
        template = self._env.get_template("dashboard.html")
        html = template.render(**ctx)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        self.log.info("HTML report → %s", output_path)
        return output_path

    def _build_context(
        self,
        docs: list[NormalizedDocument],
        result: AnalysisResult,
        board: str,
        summary_text: str,
        keyword_hits: list | None = None,
        report_title: str | None = None,
    ) -> dict:
        n_reactions = sum(len(d.reactions) for d in docs)
        post_times = sorted(d.post.post_time for d in docs)
        date_range = (
            f"{post_times[0].date()} ~ {post_times[-1].date()}"
            if post_times else "—"
        )

        if report_title is not None:
            data_source = report_title
        else:
            report_title = f"🔍 Watch Report — {board}" if board else "🔍 Watch Report"
            data_source = board or "generic"

        s = result.sentiment
        _tier_labels = {
            "core_consumer": "Core Consumer",
            "active_reviewer": "Active Reviewer",
            "engaged_participant": "Engaged Participant",
        }
        _persona_labels = {
            "brand_advocate": "Brand Advocate",
            "product_reviewer": "Product Reviewer",
            "concern_raiser": "Concern Raiser",
            "community_helper": "Community Helper",
        }
        _sentiment_icons = {
            "positive": "😊",
            "negative": "😟",
            "neutral": "😐",
            "mixed": "😐",
            "controversial": "⚡",
            "unknown": "❓",
        }
        _sentiment_labels = {
            "positive": "Mostly Positive",
            "negative": "Mostly Negative",
            "mixed": "Mixed",
            "unknown": "Neutral",
        }

        ctx: dict = dict(
            title=report_title,
            report_title=report_title,
            data_source=data_source,
            board=board,
            n_docs=len(docs),
            n_reactions=n_reactions,
            date_range=date_range,
            generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            positive_count=s.positive_count if s else 0,
            negative_count=s.negative_count if s else 0,
            controversial_count=s.controversial_count if s else 0,
            avg_score=f"{s.avg_pn_score:.3f}" if s else "—",
            suspicious_count=result.anomaly.suspicious_count if result.anomaly else 0,
            n_clusters=result.topics.n_clusters if result.topics else 0,
            summary_text=summary_text,
            plotly_js_inline=None,
            koc_profiles=result.koc.top_koc(12) if result.koc else [],
            tier_labels=_tier_labels,
            persona_labels=_persona_labels,
            sentiment_icons=_sentiment_icons,
            sentiment_labels=_sentiment_labels,
            # Charts
            chart_sentiment_donut=None,
            chart_sentiment_bar=None,
            chart_entity_bar=None,
            chart_time_series=None,
            chart_topic_bubble=None,
            chart_kol_bar=None,
            chart_anomaly_table=None,
            chart_koc_heatmap=None,
            # Keyword watch
            keyword_hits=keyword_hits or [],
            chart_keyword_bar=None,
        )

        if s:
            ctx["chart_sentiment_donut"] = charts.sentiment_donut(s)
            ctx["chart_sentiment_bar"] = charts.sentiment_bar(s)
        if result.entities:
            ctx["chart_entity_bar"] = charts.entity_bar(result.entities)
        if result.time_series:
            ctx["chart_time_series"] = charts.time_series_chart(result.time_series)
        if result.topics:
            ctx["chart_topic_bubble"] = charts.topic_bubble(result.topics)
        if result.kol:
            ctx["chart_kol_bar"] = charts.kol_bar(result.kol)
        if result.anomaly:
            ctx["chart_anomaly_table"] = charts.anomaly_table(result.anomaly)
        if result.koc:
            ctx["chart_koc_heatmap"] = charts.koc_topic_heatmap(result.koc)
        if keyword_hits:
            ctx["chart_keyword_bar"] = charts.keyword_hits_bar(keyword_hits)

        return ctx


def _get_plotly_js() -> str:
    try:
        import plotly
        plotly_dir = Path(plotly.__file__).parent
        candidates = list(plotly_dir.rglob("plotly.min.js"))
        if candidates:
            return candidates[0].read_text(encoding="utf-8")
    except Exception:
        pass
    return ""
