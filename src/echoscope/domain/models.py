from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def utcnow() -> datetime:
    return datetime.now(UTC)


class Kind(StrEnum):
    COMMENT = "COMMENT"
    REVIEW = "REVIEW"
    LIVE_CHAT = "LIVE_CHAT"
    FEED_ENTRY = "FEED_ENTRY"
    NEWS_ARTICLE = "NEWS_ARTICLE"
    YOUTUBE_VIDEO = "YOUTUBE_VIDEO"
    YOUTUBE_LIVE = "YOUTUBE_LIVE"
    FORUM_POST = "FORUM_POST"
    PRESS_COMMENT = "PRESS_COMMENT"


class State(StrEnum):
    DISABLED = "DISABLED"
    IDLE = "IDLE"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    RETRYING = "RETRYING"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"


class Availability(StrEnum):
    WAITING = "WAITING"
    LIVE = "LIVE"
    ENDED = "ENDED"
    UNAVAILABLE = "UNAVAILABLE"


class Severity(StrEnum):
    INFO = "info"
    IMPORTANT = "important"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Message:
    kind: Kind
    origin: str
    external_id: str
    resource_id: str
    text: str
    author: str | None = None
    author_id: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    captured_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True, slots=True)
class Batch:
    messages: tuple[Message, ...]
    checkpoint: str | None
    coverage_gap: bool = False


@dataclass(frozen=True, slots=True)
class Match:
    start: int
    end: int
    term: str
    rule_id: str
    rule_revision: str
    severity: Severity
    priority: int
    method: str = "exact"
    canonical: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.method != "review"


@dataclass(frozen=True, slots=True)
class Observation:
    message: Message
    matches: tuple[Match, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoryQuery:
    job_id: str | None = None
    source_id: str | None = None
    text: str | None = None
    severity: Severity | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 200
    before: int | None = None
    after: int | None = None
    matches_only: bool = False
    kind: Kind | None = None
    category: str | None = None
    review_only: bool = False


def category(kind: Kind, origin: str) -> str:
    if kind == Kind.COMMENT:
        return "youtube" if origin == "youtube:comment" else "press"
    return {
        Kind.NEWS_ARTICLE: "news",
        Kind.FEED_ENTRY: "news",
        Kind.LIVE_CHAT: "live",
        Kind.YOUTUBE_LIVE: "live",
        Kind.YOUTUBE_VIDEO: "youtube",
        Kind.FORUM_POST: "forum",
        Kind.PRESS_COMMENT: "press",
        Kind.REVIEW: "press",
    }[kind]


@dataclass(frozen=True, slots=True)
class Result:
    id: int
    job_id: str
    source_id: str
    observation: Observation
