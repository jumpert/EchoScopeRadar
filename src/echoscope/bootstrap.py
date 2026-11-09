from echoscope.application.ports import ConnectorType
from echoscope.connectors.simulated import SimParams, Simulator
from echoscope.connectors.syndication import Feed, FeedParams
from echoscope.connectors.youtube import YouTubeLive, YouTubeParams


def registry() -> dict[str, ConnectorType]:
    connectors = (
        ConnectorType("sim_poll", "poll", SimParams, Simulator, simulated=True),
        ConnectorType("sim_live", "stream", SimParams, Simulator, simulated=True),
        ConnectorType("syndication", "poll", FeedParams, Feed, ("bearer",), min_interval_s=60),
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
