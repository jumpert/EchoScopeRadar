import asyncio
import os
from dataclasses import dataclass, replace
from importlib.resources import as_file, files
from uuid import uuid4

from echoscope.bootstrap import registry
from echoscope.connectors.comment_feed import discover_comment_feed
from echoscope.connectors.syndication import public_url
from echoscope.connectors.youtube_comments import find_videos, video_id
from echoscope.storage.sqlite import Store

from .config import Configuration, Credential, Job, RuleSpec, Source, read_config
from .engine import Radar, validate_config
from .ports import AuthRequired, JobCommand

YOUTUBE_KEY = "ECHOSCOPE_YOUTUBE_KEY"
RULE_SET = "defensa"
SOURCE_TYPES = {
    "Noticias de un sitio (RSS)": ("syndication", "NEWS_ARTICLE"),
    "Comentarios de un sitio (RSS)": ("syndication", "COMMENT"),
    "Comentarios de un video de YouTube": ("youtube_comments", "COMMENT"),
    "Chat de un directo de YouTube": ("youtube_live", "LIVE_CHAT"),
}


@dataclass(frozen=True, slots=True)
class SourceForm:
    label: str
    type_label: str
    address: str
    minutes: int
    enabled: bool = True
    relevant_only: bool = False
    token_env: str = ""

    def models(self, identifier, rule_set, previous=None):
        connector, kind = SOURCE_TYPES[self.type_label]
        label = self.label.strip()
        if not label:
            raise ValueError("Escribí un nombre corto para reconocer esta fuente.")
        if not 1 <= self.minutes <= 1440 or connector == "youtube_comments" and self.minutes < 5:
            raise ValueError(
                "Elegí un intervalo entre 1 y 1440 minutos (mínimo 5 para comentarios de YouTube)."
            )
        if connector == "syndication":
            try:
                endpoint = public_url(self.address.strip())
            except ValueError:
                raise ValueError(
                    "Pegá el enlace HTTPS de un feed publicado en un dominio público."
                ) from None
            params = {"url": endpoint, "kind": kind}
            credential = (
                Credential(kind="bearer", env=self.token_env.strip())
                if self.token_env.strip()
                else None
            )
        else:
            params = {"video_id": video_id(self.address)}
            credential = Credential(kind="api_key", env=YOUTUBE_KEY)
        if previous and previous.type == connector:
            params = previous.params | params
            if connector != "syndication" and previous.credential:
                credential = previous.credential
        retention = previous.retention_days if previous else 30
        if connector == "youtube_comments":
            retention = min(retention, 7)
        source = Source(
            id=identifier,
            label=label,
            type=connector,
            params=params,
            credential=credential,
            retention_days=retention,
        )
        job = Job(
            id=identifier,
            source=identifier,
            rule_set=rule_set,
            enabled=self.enabled,
            interval_s=self.minutes * 60.0,
            relevant_only=self.relevant_only,
        )
        return source, job


class Administration:
    def __init__(self, path, practice=False):
        self.store = Store(path)
        self.practice = practice
        self.connectors = registry()
        self.guard = asyncio.Lock()
        self.worker = None
        self.radar = None
        self.context = None

    async def open(self):
        async with self.guard:
            context = self.store.opened(write=True)
            await context.__aenter__()
            self.context = context
            try:
                config = await self.store.configuration()
                if config is None:
                    filename = "demo.yaml" if self.practice else "defensa-uruguay.yaml"
                    with as_file(files("echoscope").joinpath("examples", filename)) as path:
                        config = read_config(path)
                    validate_config(config, self.connectors)
                    await self.store.configure(config)
            except BaseException:
                self.context = None
                await context.__aexit__(None, None, None)
                raise
            return config

    async def close(self):
        async with self.guard:
            try:
                await self._stop()
            finally:
                if self.context:
                    context, self.context = self.context, None
                    await context.__aexit__(None, None, None)

    async def _start(self):
        if self.worker:
            return
        radar = Radar(self.store, self.connectors)
        worker = asyncio.create_task(radar.run())
        ready = asyncio.create_task(radar.ready.wait())
        try:
            await asyncio.wait({worker, ready}, return_when=asyncio.FIRST_COMPLETED)
            if worker.done():
                await worker
            self.radar, self.worker = radar, worker
        finally:
            ready.cancel()
            await asyncio.gather(ready, return_exceptions=True)

    async def _stop(self):
        if self.worker:
            radar, worker = self.radar, self.worker
            self.radar = self.worker = None
            radar.stop()
            await worker

    async def set_running(self, enabled):
        async with self.guard:
            await (self._start() if enabled else self._stop())

    async def snapshot(self, query):
        radar = self.radar
        snapshots = dict(radar.jobs) if radar else await self.store.snapshots()
        results = await self.store.messages(query)
        if radar and query.before is None:
            for identifier in list(radar.session):
                if query.job_id in (None, identifier):
                    results += await radar.messages(replace(query, job_id=identifier))
        results.sort(key=lambda result: result.observation.message.captured_at, reverse=True)
        return snapshots, results[: query.limit], bool(radar), bool(os.environ.get(YOUTUBE_KEY))

    async def _apply(self, config):
        Configuration.model_validate(config.model_dump())
        validate_config(config, self.connectors)
        restart = bool(self.worker)
        await self._stop()
        try:
            await self.store.configure(config)
        finally:
            if restart:
                await self._start()
        return config

    async def save_source(self, form, job_id=None, token=""):
        async with self.guard:
            config = await self.store.configuration()
            old = next((job for job in config.jobs if job.id == job_id), None)
            previous = next(
                (source for source in config.sources if old and source.id == old.source), None
            )
            shared = previous and any(
                job.id != old.id and job.source == previous.id for job in config.jobs
            )
            new_id = f"fuente-{uuid4().hex[:12]}"
            identifier = previous.id if previous and not shared else new_id
            rule_set = old.rule_set if old else next(iter(config.rule_sets), RULE_SET)
            token_name = f"ECHOSCOPE_FEED_{identifier.replace('-', '_').upper()}"
            if (
                previous
                and previous.type == "syndication"
                and form.address.strip() != previous.params.get("url")
            ):
                form = replace(form, token_env="")
            if token and SOURCE_TYPES[form.type_label][0] == "syndication":
                if (
                    not token.isascii()
                    or not token.isprintable()
                    or any(char.isspace() for char in token)
                ):
                    raise ValueError("El token del feed debe ingresarse sin espacios.")
                form = replace(form, token_env=token_name)
            source, job = form.models(identifier, rule_set, previous)
            if old:
                job = job.model_copy(update={"id": old.id, "timeout_s": old.timeout_s})
            sources = [item for item in config.sources if item.id != source.id] + [source]
            jobs = [item for item in config.jobs if item.id != job.id] + [job]
            old_token = os.environ.get(token_name)
            if token and source.type == "syndication":
                os.environ[token_name] = token
            try:
                return await self._apply(
                    config.model_copy(update={"sources": sources, "jobs": jobs})
                )
            except Exception:
                if old_token is None:
                    os.environ.pop(token_name, None)
                else:
                    os.environ[token_name] = old_token
                raise

    async def remove_source(self, job_id):
        async with self.guard:
            config = await self.store.configuration()
            jobs = [job for job in config.jobs if job.id != job_id]
            removed = next((job.source for job in config.jobs if job.id == job_id), None)
            sources = [
                source
                for source in config.sources
                if source.id != removed or any(job.source == removed for job in jobs)
            ]
            return await self._apply(config.model_copy(update={"sources": sources, "jobs": jobs}))

    async def save_topic(self, phrases):
        async with self.guard:
            config = await self.store.configuration()
            name = next(iter(config.rule_sets), RULE_SET)
            prior = {rule.phrase.casefold(): rule for rule in config.rule_sets.get(name, [])}
            unique = {
                phrase.strip().casefold(): phrase.strip() for phrase in phrases if phrase.strip()
            }
            if not unique:
                raise ValueError("Escribí al menos una palabra o frase para el tema.")
            rules = [
                prior.get(key) or RuleSpec(id=f"regla-{uuid4().hex[:12]}", phrase=phrase)
                for key, phrase in unique.items()
            ]
            return await self._apply(
                config.model_copy(update={"rule_sets": config.rule_sets | {name: rules}})
            )

    async def credentials(self, key):
        if (
            not key
            or not key.isascii()
            or not key.isprintable()
            or any(char.isspace() for char in key)
        ):
            raise ValueError("Ingresá una clave de API sin espacios.")
        async with self.guard:
            os.environ[YOUTUBE_KEY] = key
            if self.radar:
                for item in list(self.radar.jobs.values()):
                    if item.job.enabled and not item.paused and item.detail == AuthRequired.label:
                        if item.source.credential and item.source.credential.env == YOUTUBE_KEY:
                            await self.radar.execute(JobCommand(item.job.id, "recover"))

    async def search(self, terms):
        if not terms.strip():
            raise ValueError("Escribí el tema que querés buscar en YouTube.")
        return await find_videos(terms.strip(), Credential(kind="api_key", env=YOUTUBE_KEY))

    async def detect_comments(self, url):
        return await discover_comment_feed(url.strip())

    async def probe(self, job_id):
        async with self.guard:
            if self.worker:
                raise ValueError("Detené el seguimiento para consultar esta fuente por separado.")
            return await Radar(self.store, self.connectors).run_once(job_id)
