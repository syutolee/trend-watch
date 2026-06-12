from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Platform(StrEnum):
    GENERIC = "generic"
    PTT = "ptt"


class Attitude(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class Post(BaseModel):
    id: str
    platform: Platform
    board: str
    title: str
    title_category: str
    author: str
    post_time: datetime
    content: str
    url: str
    engagement: dict[str, int] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=datetime.utcnow)


class Reaction(BaseModel):
    id: str
    post_id: str
    author: str
    content: str
    reaction_time: datetime | None
    attitude: Attitude
    order: int
    raw_attitude: str


class NormalizedDocument(BaseModel):
    post: Post
    reactions: list[Reaction] = Field(default_factory=list)
