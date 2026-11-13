import json

from echoscope.application.ports import Transient
from echoscope.settings import runtime_settings


async def bounded_json(response):
    body = bytearray()
    limit = runtime_settings().api_max_body_bytes
    async for chunk in response.content.iter_chunked(65536):
        body.extend(chunk)
        if len(body) > limit:
            raise Transient()
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError):
        raise Transient() from None
    if not isinstance(data, dict):
        raise Transient()
    return data
