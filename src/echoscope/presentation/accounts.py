import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
from contextlib import closing
from time import monotonic

from cryptography.fernet import Fernet

from echoscope.settings import runtime_settings

USER = re.compile(r"[a-z0-9][a-z0-9_.-]{2,39}\Z")
COOKIE = "__Host-echoscope"


def password_digest(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024)


def set_password(root, username, password):
    if not USER.fullmatch(username) or not 12 <= len(password) <= 256:
        raise ValueError(
            "Usá un usuario de 3 a 40 caracteres y una contraseña de 12 a 256 caracteres."
        )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    salt = secrets.token_bytes(16)
    digest = password_digest(password, salt)
    with closing(sqlite3.connect(root / "accounts.sqlite")) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS account (name TEXT PRIMARY KEY, salt BLOB, digest BLOB)"
        )
        conn.execute("INSERT OR REPLACE INTO account VALUES (?, ?, ?)", (username, salt, digest))


class Accounts:
    def __init__(self, root, origin, master_key, factory, *, auto_start=False):
        self.settings = runtime_settings()
        if not (root / "accounts.sqlite").is_file():
            raise ValueError("Creá al menos una cuenta antes de iniciar el servidor.")
        with closing(sqlite3.connect(root / "accounts.sqlite")) as conn:
            self.users = {
                name: (salt, digest)
                for name, salt, digest in conn.execute("SELECT name,salt,digest FROM account")
            }
        self.master = base64.b64decode(master_key, altchars=b"-_", validate=True)
        if len(self.master) != 32:
            raise ValueError(
                "La clave maestra del servidor debe contener 32 bytes en base64 URL-safe."
            )
        self.root = root
        self.origin = origin
        self.factory = factory
        self.auto_start = auto_start
        self.sessions = {}
        self.attempts = {}
        self.workspaces = {}
        self.lock = asyncio.Lock()
        self.hash_slots = asyncio.Semaphore(self.settings.password_hash_slots)

    async def authenticate(self, username, password, peer):
        now = monotonic()
        if len(self.attempts) >= 2048:
            self.attempts = {
                key: times for key, times in self.attempts.items() if times and times[-1] > now - 60
            }
            if len(self.attempts) >= 2048:
                return None
        attempts = self.attempts.setdefault(peer, [])
        attempts[:] = [stamp for stamp in attempts if stamp > now - 60]
        if len(attempts) >= self.settings.login_attempts_per_minute:
            return None
        attempts.append(now)
        if self.hash_slots.locked():
            return None
        account = self.users.get(username)
        salt, expected = account or (b"\0" * 16, b"\0" * 64)
        async with self.hash_slots:
            actual = await asyncio.to_thread(password_digest, password, salt)
        if not hmac.compare_digest(actual, expected) or account is None:
            return None
        if now in attempts:
            attempts.remove(now)
        self.sessions = {key: session for key, session in self.sessions.items() if session[1] > now}
        if len(self.sessions) >= self.settings.max_sessions:
            return None
        token = secrets.token_urlsafe(32)
        self.sessions[token] = (username, now + self.settings.session_ttl_s)
        return token

    def username(self, token):
        session = self.sessions.get(token)
        if session and session[1] > monotonic():
            return session[0]
        self.sessions.pop(token, None)
        return None

    async def workspace(self, username):
        async with self.lock:
            if username not in self.workspaces:
                if len(self.workspaces) >= self.settings.max_workspaces:
                    raise ValueError("Se alcanzó la capacidad de espacios activos del servidor.")
                digest = hmac.digest(self.master, b"echoscope-vault:" + username.encode(), "sha256")
                directory = hashlib.sha256(username.encode()).hexdigest()
                state = self.factory(
                    self.root / "users" / directory / "radar.sqlite",
                    False,
                    self.auto_start,
                    username=username,
                    cipher=Fernet(base64.urlsafe_b64encode(digest)),
                )
                await state.open()
                self.workspaces[username] = state
            return self.workspaces[username]

    async def lifecycle(self, _app):
        try:
            for username in self.users:
                directory = hashlib.sha256(username.encode()).hexdigest()
                path = self.root / "users" / directory / "radar.sqlite"
                if not path.is_file():
                    continue
                with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                    enabled = conn.execute(
                        "SELECT value FROM desktop_settings WHERE key='monitoring_enabled'"
                    ).fetchone()
                if enabled and enabled[0] == "true":
                    await self.workspace(username)
            yield
        finally:
            await asyncio.gather(*(state.service.close() for state in self.workspaces.values()))
