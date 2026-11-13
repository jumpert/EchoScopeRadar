from echoscope.application.ports import ConnectorType
from echoscope.connectors.bluesky import BlueskyParams, BlueskyThread
from echoscope.connectors.pending import PendingConnector, PendingParams
from echoscope.connectors.press_feed import PressFeed
from echoscope.connectors.simulated import SimParams, Simulator
from echoscope.connectors.syndication import Feed, FeedParams
from echoscope.connectors.youtube import YouTubeLive, YouTubeParams
from echoscope.connectors.youtube_channel import ChannelParams, YouTubeChannel, YouTubeChannelLive
from echoscope.connectors.youtube_comments import YouTubeComments, YouTubeCommentsParams
from echoscope.storage.factory import create_store

__all__ = ["create_store", "registry"]


def registry() -> dict[str, ConnectorType]:
    connectors = (
        ConnectorType("pending_social", "poll", PendingParams, PendingConnector, min_interval_s=60),
        ConnectorType("sim_poll", "poll", SimParams, Simulator, simulated=True),
        ConnectorType("sim_live", "stream", SimParams, Simulator, simulated=True),
        ConnectorType(
            "syndication",
            "poll",
            FeedParams,
            Feed,
            ("bearer",),
            min_interval_s=60,
            capabilities=("publications", "comments", "recovery_window"),
        ),
        ConnectorType(
            "press_feed",
            "poll",
            FeedParams,
            PressFeed,
            ("bearer",),
            min_interval_s=60,
            capabilities=("publications", "comments", "replies", "recovery_window"),
        ),
        ConnectorType("bluesky_thread", "poll", BlueskyParams, BlueskyThread, min_interval_s=60),
        ConnectorType(
            "youtube_channel",
            "poll",
            ChannelParams,
            YouTubeChannel,
            ("api_key", "oauth"),
            min_interval_s=300,
            capabilities=("publications", "comments", "replies", "recovery_window"),
        ),
        ConnectorType(
            "youtube_channel_live",
            "stream",
            ChannelParams,
            YouTubeChannelLive,
            ("api_key", "oauth"),
            persistent=False,
            min_interval_s=1800,
            capabilities=("publications", "live_chat"),
        ),
        ConnectorType(
            "youtube_comments",
            "poll",
            YouTubeCommentsParams,
            YouTubeComments,
            ("api_key", "oauth"),
            min_interval_s=300,
            capabilities=("comments", "replies", "recovery_window"),
        ),
        ConnectorType(
            "youtube_live",
            "stream",
            YouTubeParams,
            YouTubeLive,
            ("api_key", "oauth"),
            persistent=False,
            min_interval_s=60,
            capabilities=("live_chat",),
        ),
    )
    return {connector.name: connector for connector in connectors}
