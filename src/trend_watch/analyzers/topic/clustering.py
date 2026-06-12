from __future__ import annotations

from dataclasses import dataclass, field

from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from trend_watch.analyzers.topic.embedding import TFIDFEmbedder
from trend_watch.models import NormalizedDocument
from trend_watch.utils.logging import LoggerMixin


@dataclass
class TopicCluster:
    cluster_id: int
    label: str
    keywords: list[str]
    post_ids: list[str] = field(default_factory=list)
    size: int = 0


@dataclass
class ClusteringReport:
    clusters: list[TopicCluster] = field(default_factory=list)
    n_clusters: int = 0
    silhouette: float = 0.0

    def get_cluster(self, post_id: str) -> TopicCluster | None:
        return next((c for c in self.clusters if post_id in c.post_ids), None)


def _auto_k(n_docs: int) -> int:
    return max(2, min(10, int((n_docs / 2) ** 0.5)))


class TopicClusterer(LoggerMixin):

    def __init__(self, n_clusters: int | None = None, max_features: int = 500) -> None:
        self._n_clusters = n_clusters
        self._max_features = max_features

    def analyze(self, docs: list[NormalizedDocument]) -> ClusteringReport:
        if len(docs) < 4:
            self.log.warning("Too few docs (%d) for clustering", len(docs))
            return ClusteringReport()

        embedder = TFIDFEmbedder(max_features=self._max_features)
        matrix = embedder.fit_transform(docs)
        feature_names = embedder.feature_names

        k = self._n_clusters or _auto_k(len(docs))
        k = min(k, len(docs) - 1)

        km = KMeans(n_clusters=k, random_state=42, n_init="auto")
        labels = km.fit_predict(matrix)

        sil = 0.0
        if k > 1 and len(set(labels)) > 1:
            sil = float(silhouette_score(matrix, labels))

        clusters: list[TopicCluster] = []
        for cid in range(k):
            mask = labels == cid
            post_ids = [docs[i].post.id for i in range(len(docs)) if mask[i]]
            centroid = km.cluster_centers_[cid]
            top_idx = centroid.argsort()[-10:][::-1]
            keywords = [feature_names[i] for i in top_idx]
            label = " / ".join(keywords[:3])
            clusters.append(TopicCluster(
                cluster_id=cid,
                label=label,
                keywords=keywords,
                post_ids=post_ids,
                size=len(post_ids),
            ))

        clusters.sort(key=lambda c: c.size, reverse=True)
        self.log.info(
            "Clustering: k=%d, silhouette=%.3f, sizes=%s",
            k, sil, [c.size for c in clusters],
        )
        return ClusteringReport(clusters=clusters, n_clusters=k, silhouette=sil)
