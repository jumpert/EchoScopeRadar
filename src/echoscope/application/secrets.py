import os
from contextvars import ContextVar

account_secrets: ContextVar[dict[str, str] | None] = ContextVar("account_secrets", default=None)


def secrets_for_request():
    scoped = account_secrets.get()
    return os.environ if scoped is None else scoped
