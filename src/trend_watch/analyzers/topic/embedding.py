from __future__ import annotations

import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from trend_watch.models import NormalizedDocument
from trend_watch.utils.logging import LoggerMixin

_STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都",
    "一", "一個", "上", "也", "很", "到", "說", "要", "去", "你",
    "會", "著", "沒有", "看", "好", "自己", "這", "那", "之", "與",
    "但", "可以", "如果", "因為", "所以", "而且", "還是", "只是",
    "http", "https", "com", "www",
}


def _tokenize(text: str) -> str:
    tokens = jieba.cut(text, cut_all=False)
    return " ".join(t for t in tokens if t.strip() and t not in _STOPWORDS and len(t) > 1)


class TFIDFEmbedder(LoggerMixin):

    def __init__(self, max_features: int = 500) -> None:
        self._max_features = max_features
        self._vectorizer: TfidfVectorizer | None = None

    def fit_transform(self, docs: list[NormalizedDocument]) -> np.ndarray:
        corpus = [self._doc_to_text(d) for d in docs]
        tokenised = [_tokenize(t) for t in corpus]

        self._vectorizer = TfidfVectorizer(
            max_features=self._max_features,
            min_df=1,
            sublinear_tf=True,
        )
        matrix = self._vectorizer.fit_transform(tokenised)
        self.log.info("TF-IDF matrix: %s", matrix.shape)
        return matrix.toarray()

    @property
    def feature_names(self) -> list[str]:
        if self._vectorizer is None:
            raise RuntimeError("Call fit_transform first")
        return list(self._vectorizer.get_feature_names_out())

    def _doc_to_text(self, doc: NormalizedDocument) -> str:
        title = doc.post.title + " " + doc.post.title
        content = doc.post.content[:300]
        reactions = " ".join(r.content for r in doc.reactions[:20])
        return f"{title} {content} {reactions}"
