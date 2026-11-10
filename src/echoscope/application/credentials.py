import json
import os
from uuid import uuid4

from cryptography.fernet import InvalidToken

from .administration import YOUTUBE_KEY
from .secrets import secrets_for_request

PROVIDERS = {
    "youtube": ("YouTube Data API", YOUTUBE_KEY),
    "brave": ("Brave Search", "ECHOSCOPE_BRAVE_KEY"),
    "tavily": ("Tavily", "ECHOSCOPE_TAVILY_KEY"),
    "serper": ("Google mediante Serper", "ECHOSCOPE_SERPER_KEY"),
}


class CredentialVault:
    def __init__(self, store, cipher=None):
        self.store = store
        self.cipher = cipher
        self.entries = {}
        self.active = {}
        self.initial = {}

    async def load(self):
        self.initial = {env: secrets_for_request().get(env) for _, env in PROVIDERS.values()}
        encoded = await self.store.desktop_setting("credential_vault") if self.cipher else None
        if encoded:
            try:
                data = json.loads(self.cipher.decrypt(encoded.encode()))
            except (InvalidToken, ValueError):
                raise ValueError(
                    "No se pudo abrir el almacén de claves con la clave maestra configurada."
                ) from None
            self.entries, self.active = data["entries"], data["active"]
        self.apply()

    def apply(self):
        environment = secrets_for_request()
        for provider, (_, env) in PROVIDERS.items():
            identifier = self.active.get(provider)
            value = self.entries[identifier]["value"] if identifier else self.initial.get(env)
            if value:
                environment[env] = value
            else:
                environment.pop(env, None)

    def public(self):
        return {
            "persistent": self.cipher is not None,
            "searx_available": bool(os.environ.get("ECHOSCOPE_SEARXNG_URL")),
            "providers": [
                {"id": key, "label": label, "available": bool(secrets_for_request().get(env))}
                for key, (label, env) in PROVIDERS.items()
            ],
            "entries": [
                {
                    "id": identifier,
                    "provider": entry["provider"],
                    "name": entry["name"],
                    "active": self.active.get(entry["provider"]) == identifier,
                }
                for identifier, entry in self.entries.items()
            ],
        }

    async def save(self, entries, active):
        if self.cipher:
            data = json.dumps({"entries": entries, "active": active}).encode()
            await self.store.set_desktop_setting(
                "credential_vault", self.cipher.encrypt(data).decode()
            )
        self.entries, self.active = entries, active
        self.apply()

    async def add(self, provider, name, value):
        if provider not in PROVIDERS or len(self.entries) >= 50:
            raise ValueError("Revisá el proveedor o quitá una clave antes de agregar otra.")
        if not value.isascii() or not value.isprintable() or any(char.isspace() for char in value):
            raise ValueError("Ingresá una clave sin espacios.")
        identifier = uuid4().hex
        await self.save(
            self.entries | {identifier: {"name": name, "provider": provider, "value": value}},
            self.active | ({provider: identifier} if provider not in self.active else {}),
        )

    async def change(self, identifier, *, remove=False):
        if identifier not in self.entries:
            raise ValueError("La clave seleccionada ya no está disponible.")
        provider = self.entries[identifier]["provider"]
        entries, active = dict(self.entries), dict(self.active)
        if remove:
            del entries[identifier]
            if active.get(provider) == identifier:
                active.pop(provider)
        else:
            active[provider] = identifier
        await self.save(entries, active)
