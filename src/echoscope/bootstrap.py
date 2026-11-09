from echoscope.application.ports import ConnectorType
from echoscope.connectors.simulated import SimParams, Simulator
from echoscope.connectors.syndication import Feed, FeedParams
from echoscope.connectors.youtube import YouTubeLive, YouTubeParams
from echoscope.connectors.youtube_comments import YouTubeComments, YouTubeCommentsParams


def registry() -> dict[str, ConnectorType]:
    connectors = (
        ConnectorType("sim_poll", "poll", SimParams, Simulator, simulated=True),
        ConnectorType("sim_live", "stream", SimParams, Simulator, simulated=True),
        ConnectorType("syndication", "poll", FeedParams, Feed, ("bearer",), min_interval_s=60),
        ConnectorType(
            "youtube_comments",
            "poll",
            YouTubeCommentsParams,
            YouTubeComments,
            ("api_key", "oauth"),
            min_interval_s=300,
        ),
        ConnectorType(
            "youtube_live",
            "stream",
            YouTubeParams,
            YouTubeLive,
            ("api_key", "oauth"),
            persistent=False,
            min_interval_s=60,
        ),
    )
    return {connector.name: connector for connector in connectors}
