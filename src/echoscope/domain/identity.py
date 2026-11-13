import json
from hashlib import sha256


def alert_identity(job, origin, external_id, body):
    return sha256(
        json.dumps((job, origin, external_id, body), ensure_ascii=False).encode()
    ).hexdigest()


def alert_key(result):
    message = result.observation.message
    return alert_identity(result.job_id, message.origin, message.external_id, message.text)
