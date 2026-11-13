from typing import Literal

from pydantic import Field, model_validator

from echoscope.application.config import StrictModel
from echoscope.application.ports import ConnectorError

from .syndication import public_url

PLATFORMS = (
    "Facebook",
    "Instagram",
    "X",
    "TikTok",
    "Threads",
    "Reddit",
    "Telegram",
    "Canales de WhatsApp",
)


class PendingParams(StrictModel):
    platform: Literal[
        "Facebook",
        "Instagram",
        "X",
        "TikTok",
        "Threads",
        "Reddit",
        "Telegram",
        "Canales de WhatsApp",
    ]
    url: str
    resource_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_url(self):
        public_url(self.url)
        return self


class PendingAccess(ConnectorError):
    label = "ACCESO PENDIENTE · REQUIERE CONECTOR Y PERMISOS"


class PendingConnector:
    async def poll(self, request):
        raise PendingAccess()
        yield  # Makes the connector follow the async-iterator contract.
