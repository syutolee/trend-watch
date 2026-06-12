from __future__ import annotations

from dataclasses import dataclass, field

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer

from trend_watch.models import NormalizedDocument
from trend_watch.utils.logging import LoggerMixin

_STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都",
    "一", "上", "也", "很", "到", "說", "要", "去", "你", "會",
    "著", "沒有", "看", "好", "自己", "這", "那", "之", "與",
    "但", "可以", "如果", "因為", "所以", "而且", "還是", "只是",
    "http", "https", "com", "www",
}


@dataclass
class KeywordFrequency:
    term: str
    tfidf_score: float
    raw_count: int


@dataclass
class WordCloudData:
    weights: dict[str, float] = field(default_factory=dict)
    top_keywords: list[KeywordFrequency] = field(default_factory=list)


class KeywordExtractor(LoggerMixin):

    def extract(self, docs: list[NormalizedDocument], top_n: int = 50) -> WordCloudData:
        corpus = []
        for doc in docs:
            text = doc.post.title + " " + doc.post.content
            text += " " + " ".join(r.content for r in doc.reactions[:30])
            corpus.append(text)

        tokenised = [self._tokenize(t) for t in corpus]
        if not any(tokenised):
            return WordCloudData()

        vec = TfidfVectorizer(max_features=200, min_df=1, sublinear_tf=True)
        matrix = vec.fit_transform(tokenised)
        feature_names = vec.get_feature_names_out()
        mean_tfidf = matrix.mean(axis=0).A1

        raw_texts = " ".join(corpus)
        raw_counts: dict[str, int] = {term: raw_texts.count(term) for term in feature_names}

        scored = sorted(
            zip(feature_names, mean_tfidf, strict=False),
            key=lambda x: x[1],
            reverse=True,
        )[:top_n]

        keywords = [
            KeywordFrequency(term=t, tfidf_score=round(float(s), 6), raw_count=raw_counts.get(t, 0))
            for t, s in scored
        ]
        weights = {kw.term: kw.tfidf_score for kw in keywords}

        self.log.info("Extracted %d keywords", len(keywords))
        return WordCloudData(weights=weights, top_keywords=keywords)

    @staticmethod
    def _tokenize(text: str) -> str:
        tokens = jieba.cut(text, cut_all=False)
        return " ".join(t for t in tokens if t.strip() and t not in _STOPWORDS and len(t) > 1)
