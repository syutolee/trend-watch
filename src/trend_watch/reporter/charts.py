from __future__ import annotations

import json

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from trend_watch.analyzers.anomaly import AnomalyReport
from trend_watch.analyzers.entity.extractor import EntityReport
from trend_watch.analyzers.koc import KOCReport, _is_genuine_user
from trend_watch.analyzers.kol import KOLReport
from trend_watch.analyzers.sentiment.pn_ratio import SentimentReport
from trend_watch.analyzers.topic.clustering import ClusteringReport
from trend_watch.analyzers.time_series import TimeSeriesReport

_COLORS = {
    "positive": "#2ecc71",
    "negative": "#e74c3c",
    "neutral": "#95a5a6",
    "controversial": "#f39c12",
}


def _fig_json(fig: go.Figure) -> str:
    return json.dumps(fig.to_dict(), ensure_ascii=False)


def sentiment_donut(report: SentimentReport) -> str:
    labels = ["Positive", "Negative", "Neutral", "Controversial"]
    values = [
        report.positive_count,
        report.negative_count,
        report.neutral_count,
        report.controversial_count,
    ]
    colors = [_COLORS["positive"], _COLORS["negative"], _COLORS["neutral"], _COLORS["controversial"]]
    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.45,
        marker_colors=colors,
        textinfo="label+percent",
        hovertemplate="%{label}: %{value} posts<extra></extra>",
    ))
    fig.update_layout(
        title="Sentiment Distribution",
        showlegend=True,
        margin=dict(t=60, b=20, l=20, r=20),
        height=350,
    )
    return _fig_json(fig)


def sentiment_bar(report: SentimentReport, n: int = 10) -> str:
    engaged = [p for p in report.posts if (p.push + p.boo) >= 3]
    top_pos = sorted(engaged, key=lambda p: p.pn_score, reverse=True)[:n] if engaged else report.top_positive(n)
    top_neg = sorted(engaged, key=lambda p: p.pn_score)[:n] if engaged else report.top_negative(n)

    fig = make_subplots(rows=1, cols=2, subplot_titles=("Most Positive Posts", "Most Negative Posts"))
    fig.add_trace(go.Bar(
        x=[p.pn_score for p in top_pos],
        y=[p.title[:30] for p in top_pos],
        orientation="h",
        marker_color=_COLORS["positive"],
        name="Positive",
        hovertemplate="%{y}<br>Score: %{x:.3f}<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=[p.pn_score for p in top_neg],
        y=[p.title[:30] for p in top_neg],
        orientation="h",
        marker_color=_COLORS["negative"],
        name="Negative",
        hovertemplate="%{y}<br>Score: %{x:.3f}<extra></extra>",
    ), row=1, col=2)
    fig.update_layout(
        title="Sentiment Ranking",
        height=400, showlegend=False,
        margin=dict(t=80, b=20, l=20, r=20),
    )
    return _fig_json(fig)


def time_series_chart(report: TimeSeriesReport, top_n: int = 6) -> str:
    if not report.series:
        return _fig_json(go.Figure())

    sorted_series = sorted(report.series, key=lambda s: s.total, reverse=True)[:top_n]
    fig = go.Figure()

    if report.volume:
        periods = list(report.volume.keys())
        counts = list(report.volume.values())
        fig.add_trace(go.Scatter(
            x=periods, y=counts,
            name="Total Posts",
            fill="tozeroy",
            fillcolor="rgba(180,180,180,0.15)",
            line=dict(color="rgba(150,150,150,0.5)", width=1),
            yaxis="y2",
        ))

    for ts in sorted_series:
        if not ts.counts:
            continue
        fig.add_trace(go.Scatter(
            x=list(ts.counts.keys()),
            y=list(ts.counts.values()),
            name=ts.term,
            mode="lines+markers",
            hovertemplate=f"{ts.term}<br>%{{x}}: %{{y}} times<extra></extra>",
        ))

    fig.update_layout(
        title="Keyword Volume Over Time",
        xaxis_title="Period",
        yaxis_title="Mentions",
        yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Total Posts"),
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=80, b=40, l=40, r=40),
        hovermode="x unified",
    )
    return _fig_json(fig)


def entity_bar(report: EntityReport, top_n: int = 10) -> str:
    cats_in_report: set[str] = set()
    for post in report.posts:
        for m in post.mentions:
            cats_in_report.add(m.category)
    categories = sorted(cats_in_report)
    if not categories:
        return _fig_json(go.Figure())

    n = len(categories)
    cols = min(n, 2)
    rows = (n + 1) // 2

    fig = make_subplots(rows=rows, cols=cols, subplot_titles=categories)
    palette = ["#3498db", "#9b59b6", "#1abc9c", "#e67e22", "#e74c3c", "#f39c12"]

    for idx, cat in enumerate(categories):
        row, col = divmod(idx, cols)
        top = report.top_terms(cat, top_n)
        if not top:
            continue
        terms, counts = zip(*top, strict=False)
        fig.add_trace(go.Bar(
            x=list(counts),
            y=list(terms),
            orientation="h",
            marker_color=palette[idx % len(palette)],
            name=cat,
            hovertemplate="%{y}: %{x} times<extra></extra>",
        ), row=row + 1, col=col + 1)

    fig.update_layout(
        title="Entity Mention Frequency",
        height=max(400, 280 * rows),
        showlegend=False,
        margin=dict(t=80, b=20, l=20, r=20),
    )
    return _fig_json(fig)


def topic_bubble(report: ClusteringReport) -> str:
    if not report.clusters:
        return _fig_json(go.Figure())

    import math
    n = len(report.clusters)
    xs = [math.cos(2 * math.pi * i / n) for i in range(n)]
    ys = [math.sin(2 * math.pi * i / n) for i in range(n)]
    sizes = [c.size for c in report.clusters]
    labels = [c.label for c in report.clusters]
    ids = [f"Cluster {c.cluster_id + 1}" for c in report.clusters]

    fig = go.Figure(go.Scatter(
        x=xs, y=ys,
        mode="markers+text",
        marker=dict(
            size=[max(20, min(80, s * 5)) for s in sizes],
            color=list(range(n)),
            colorscale="Viridis",
            sizemode="diameter",
        ),
        text=ids,
        textposition="top center",
        customdata=list(zip(labels, sizes, strict=False)),
        hovertemplate="<b>%{text}</b><br>Keywords: %{customdata[0]}<br>Posts: %{customdata[1]}<extra></extra>",
    ))
    fig.update_layout(
        title=f"Topic Clusters ({n} groups, Silhouette={report.silhouette:.3f})",
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        height=450,
        margin=dict(t=80, b=20, l=20, r=20),
    )
    return _fig_json(fig)


def kol_bar(report: KOLReport, top_n: int = 10) -> str:
    top = [p for p in report.top_by_influence(top_n * 3) if _is_genuine_user(p.user_id)][:top_n]
    if not top:
        return _fig_json(go.Figure())

    fig = go.Figure()
    users = [p.user_id for p in top]
    fig.add_trace(go.Bar(
        name="Influence Score", x=[p.influence_score for p in top], y=users,
        orientation="h", marker_color="#3498db",
        hovertemplate="%{y}: %{x:.3f}<extra></extra>",
    ))
    fig.update_layout(
        title="User Influence Ranking (Top 10)",
        xaxis_title="Score",
        height=400,
        margin=dict(t=60, b=20, l=20, r=20),
    )
    return _fig_json(fig)


def anomaly_table(report: AnomalyReport, top_n: int = 10) -> str:
    suspicious = sorted(
        report.suspicious_posts, key=lambda f: f.risk_score, reverse=True
    )[:top_n]

    if not suspicious:
        fig = go.Figure(go.Table(
            header=dict(values=["Anomaly Detection"], fill_color="#2ecc71"),
            cells=dict(values=[["No suspicious posts detected"]], fill_color="#f0fff0"),
        ))
    else:
        fig = go.Figure(go.Table(
            header=dict(
                values=["Title", "Risk Score", "Signals"],
                fill_color="#e74c3c",
                font=dict(color="white"),
            ),
            cells=dict(values=[
                [f.title[:30] for f in suspicious],
                [f"{f.risk_score:.2f}" for f in suspicious],
                ["; ".join(f.flags[:2]) for f in suspicious],
            ]),
        ))

    fig.update_layout(
        title=f"Anomaly Detection ({report.suspicious_count} suspicious posts)",
        height=350,
        margin=dict(t=60, b=10, l=10, r=10),
    )
    return _fig_json(fig)


def koc_topic_heatmap(report: KOCReport, top_n: int = 15) -> str:
    top = report.top_koc(top_n)
    if not top:
        return _fig_json(go.Figure())

    all_cats: list[str] = sorted({cat for p in top for cat in p.top_entities})
    if not all_cats:
        return _fig_json(go.Figure())

    users = [p.user_id for p in top]
    z: list[list[int]] = []
    for p in top:
        row = [
            sum(count for _, count in p.top_entities.get(cat, []))
            for cat in all_cats
        ]
        z.append(row)

    fig = go.Figure(go.Heatmap(
        z=z, x=all_cats, y=users,
        colorscale="Blues",
        hovertemplate="User: %{y}<br>Category: %{x}<br>Mentions: %{z}<extra></extra>",
        showscale=True,
    ))
    fig.update_layout(
        title="KOC Topic Affinity",
        xaxis_title="Topic Category",
        yaxis=dict(autorange="reversed"),
        height=max(350, 30 * len(users) + 120),
        margin=dict(t=60, b=60, l=100, r=40),
    )
    return _fig_json(fig)


def keyword_hits_bar(hits: list) -> str:  # list[KeywordHit]
    """Stacked bar: positive / negative / neutral / controversial per keyword."""
    if not hits:
        return _fig_json(go.Figure())

    keywords = [h.keyword for h in hits]
    pos = [h.sentiment_counts.get("positive", 0) for h in hits]
    neg = [h.sentiment_counts.get("negative", 0) for h in hits]
    neu = [h.sentiment_counts.get("neutral", 0) for h in hits]
    con = [h.sentiment_counts.get("controversial", 0) for h in hits]

    fig = go.Figure(data=[
        go.Bar(name="Positive", x=keywords, y=pos, marker_color=_COLORS["positive"]),
        go.Bar(name="Negative", x=keywords, y=neg, marker_color=_COLORS["negative"]),
        go.Bar(name="Neutral", x=keywords, y=neu, marker_color=_COLORS["neutral"]),
        go.Bar(name="Controversial", x=keywords, y=con, marker_color=_COLORS["controversial"]),
    ])
    fig.update_layout(
        barmode="stack",
        title="Keyword Hit Sentiment Distribution",
        xaxis_title="Keyword",
        yaxis_title="Article Count",
        height=380,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=80, b=40, l=40, r=20),
    )
    return _fig_json(fig)
