import asyncio
from dataclasses import dataclass, replace
from importlib.resources import as_file, files
from uuid import uuid4

from echoscope.bootstrap import registry
from echoscope.connectors.bluesky import BlueskyParams
from echoscope.connectors.comment_feed import discover_comment_feed, discover_discussion_feeds
from echoscope.connectors.syndication import public_url
from echoscope.connectors.youtube_channel import channel_reference, check_access
from echoscope.connectors.youtube_comments import find_videos, video_id
from echoscope.storage.sqlite import Store

from .config import Configuration, Credential, Job, RuleSpec, Source, read_config
from .engine import Radar, validate_config
from .ports import AuthRequired, Forbidden, JobCommand
from .secrets import secrets_for_request

YOUTUBE_KEY = "ECHOSCOPE_YOUTUBE_KEY"
RULE_SET = "defensa"
SOURCE_TYPES = {
    "Noticias de un sitio (RSS)": ("press_feed", "NEWS_ARTICLE"),
    "Comentarios de un sitio (RSS)": ("syndication", "PRESS_COMMENT"),
    "Reseñas de un sitio (RSS/Atom)": ("syndication", "REVIEW"),
    "Foro o comunidad (RSS/Atom)": ("syndication", "FORUM_POST"),
    "Respuestas de una publicación de Bluesky": ("bluesky_thread", "SOCIAL_COMMENT"),
    "Comentarios de un video de YouTube": ("youtube_comments", "COMMENT"),
    "Chat de un directo de YouTube": ("youtube_live", "LIVE_CHAT"),
    "Canal de YouTube · videos automáticos": ("youtube_channel", "YOUTUBE_VIDEO"),
    "Canal de YouTube · directos automáticos": ("youtube_channel_live", "LIVE_CHAT"),
}
RSS_TYPES = {"syndication", "press_feed"}
CHANNEL_TYPES = {"youtube_channel", "youtube_channel_live"}


def _example(filename):
    with as_file(files("echoscope").joinpath("examples", filename)) as path:
        return read_config(path)


def upgrade_desktop_profile(config):
    if config.desktop_profile:
        return config
    preset = _example("defensa-uruguay.yaml")
    by_id = {item.id: item for item in preset.sources}
    managed = {
        item.id
        for item in config.sources
        if item.id in by_id
        and item.type == "syndication"
        and item.params.get("kind") == "NEWS_ARTICLE"
        and item.params.get("url") == by_id[item.id].params.get("url")
    }
    sources = [
        item.model_copy(update={"type": "press_feed"}) if item.id in managed else item
        for item in config.sources
    ]
    jobs = list(config.jobs)
    rule_sets = {
        name: [item.model_copy(update={"detect_variants": True}) for item in rules]
        for name, rules in config.rule_sets.items()
    }
    if managed and RULE_SET in rule_sets:
        known = {item.id for item in (*sources, *jobs)}
        for source, job in zip(preset.sources, preset.jobs):
            if source.type in CHANNEL_TYPES and source.id not in known:
                sources.append(source)
                jobs.append(job)
        terms = {item.phrase.casefold() for item in rule_sets[RULE_SET]}
        ids = {item.id for item in rule_sets[RULE_SET]}
        rule_sets[RULE_SET] += [
            item
            for item in preset.rule_sets[RULE_SET]
            if item.id in {"defensa", "soldado"}
            and item.id not in ids
            and item.phrase.casefold() not in terms
        ]
    return config.model_copy(
        update={"desktop_profile": 1, "sources": sources, "jobs": jobs, "rule_sets": rule_sets}
    )


def expand_national_profile(config):
    if config.desktop_profile == 2 or RULE_SET not in config.rule_sets:
        return config
    if not {"telenoche", "subrayado", "montevideo-portal", "el-observador"}.intersection(
        source.id for source in config.sources
    ):
        return config
    preset = _example("defensa-uruguay.yaml")
    known = {item.id for item in (*config.sources, *config.jobs)}
    urls = {source.params.get("url") for source in config.sources}
    additions = {"la-diaria", "brecha", "caras-caretas", "teledoce"}
    sources = [
        source
        for source in preset.sources
        if source.id in additions - known and source.params["url"] not in urls
    ]
    ids = {source.id for source in sources}
    return config.model_copy(
        update={
            "desktop_profile": 2,
            "sources": [*config.sources, *sources],
            "jobs": [*config.jobs, *(job for job in preset.jobs if job.source in ids)],
        }
    )


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
        minimum = (
            30
            if connector == "youtube_channel_live"
            else 5
            if connector in {"youtube_comments", "youtube_channel"}
            else 1
        )
        if not minimum <= self.minutes <= 1440:
            raise ValueError(f"Elegí un intervalo entre {minimum} y 1440 minutos para esta fuente.")
        if connector in RSS_TYPES:
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
        elif connector == "bluesky_thread":
            params = BlueskyParams(url=self.address).model_dump()
            credential = None
        elif connector in CHANNEL_TYPES:
            params = {"channel": channel_reference(self.address)}
            credential = Credential(kind="api_key", env=YOUTUBE_KEY)
        else:
            params = {"video_id": video_id(self.address)}
            credential = Credential(kind="api_key", env=YOUTUBE_KEY)
        if previous and previous.type == connector:
            params = previous.params | params
            if connector not in RSS_TYPES and previous.credential:
                credential = previous.credential
        retention = previous.retention_days if previous else 30
        if connector in {"youtube_comments", "youtube_channel"}:
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
                    config = _example("demo.yaml" if self.practice else "defensa-uruguay.yaml")
                    validate_config(config, self.connectors)
                    await self.store.configure(config)
                elif not config.desktop_profile:
                    if self.practice:
                        rules = config.rule_sets.get("avisos", [])
                        keys = {rule.id for rule in rules}
                        terms = {rule.phrase.casefold() for rule in rules}
                        additions = [
                            rule
                            for rule in _example("demo.yaml").rule_sets["avisos"]
                            if rule.detect_variants
                            and rule.id not in keys
                            and rule.phrase.casefold() not in terms
                        ]
                        config = config.model_copy(
                            update={
                                "desktop_profile": 1,
                                "rule_sets": config.rule_sets | {"avisos": [*rules, *additions]},
                            }
                        )
                    else:
                        config = upgrade_desktop_profile(config)
                    config = Configuration.model_validate(config.model_dump())
                    validate_config(config, self.connectors)
                    await self.store.configure(config)
                if (
                    not self.practice
                    and (expanded := expand_national_profile(config)) is not config
                ):
                    config = Configuration.model_validate(expanded.model_dump())
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
            if secrets_for_request().get(YOUTUBE_KEY):
                await self._recover_youtube()
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
        results = await self.messages(query)
        return snapshots, results, bool(radar), bool(secrets_for_request().get(YOUTUBE_KEY))

    async def messages(self, query):
        radar = self.radar
        results = await self.store.messages(query)
        if radar and query.before is None:
            for identifier in list(radar.session):
                if query.job_id in (None, identifier):
                    results += await radar.messages(replace(query, job_id=identifier))
        results.sort(key=lambda result: result.observation.message.captured_at, reverse=True)
        return results[: query.limit]

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
                and previous.type in RSS_TYPES
                and form.address.strip() != previous.params.get("url")
            ):
                form = replace(form, token_env="")
            if token and SOURCE_TYPES[form.type_label][0] in RSS_TYPES:
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
            environment = secrets_for_request()
            old_token = environment.get(token_name)
            if token and source.type in RSS_TYPES:
                environment[token_name] = token
            try:
                return await self._apply(
                    config.model_copy(update={"sources": sources, "jobs": jobs})
                )
            except Exception:
                if old_token is None:
                    environment.pop(token_name, None)
                else:
                    environment[token_name] = old_token
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
            unique = {}
            for line in phrases:
                if not line.strip():
                    continue
                phrase, *aliases = (part.strip() for part in line.split("|"))
                if not phrase:
                    raise ValueError("Escribí el término principal antes de la barra vertical.")
                key = phrase.casefold()
                if key not in unique:
                    unique[key] = phrase, []
                known = {item.casefold() for item in unique[key][1]}
                for alias in aliases:
                    if alias and alias.casefold() not in known | {key}:
                        unique[key][1].append(alias)
                        known.add(alias.casefold())
            if not unique:
                raise ValueError("Escribí al menos una palabra o frase para el tema.")
            rules = [
                RuleSpec.model_validate(
                    (
                        prior[key].model_dump()
                        if key in prior
                        else {"id": f"regla-{uuid4().hex[:12]}"}
                    )
                    | {"phrase": phrase, "aliases": aliases, "detect_variants": True}
                )
                for key, (phrase, aliases) in unique.items()
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
            secrets_for_request()[YOUTUBE_KEY] = key
            await self._recover_youtube()

    async def _recover_youtube(self):
        if self.radar:
            for item in tuple(self.radar.jobs.values()):
                if (
                    item.job.enabled
                    and not item.paused
                    and item.detail in {AuthRequired.label, Forbidden.label}
                    and item.source.credential
                    and item.source.credential.env == YOUTUBE_KEY
                ):
                    await self.radar.execute(JobCommand(item.job.id, "recover"))

    async def search(self, terms, *, live=False):
        if not terms.strip():
            raise ValueError("Escribí el tema que querés buscar en YouTube.")
        return await find_videos(
            terms.strip(), Credential(kind="api_key", env=YOUTUBE_KEY), live=live
        )

    async def detect_comments(self, url):
        return await discover_comment_feed(url.strip())

    async def detect_reviews(self, url):
        feeds = await discover_discussion_feeds(url.strip())
        return next((address for address, kind in feeds if kind == "REVIEW"), None)

    async def check_youtube(self):
        await check_access(Credential(kind="api_key", env=YOUTUBE_KEY))

    async def run_source(self, job_id):
        async with self.guard:
            if not self.radar:
                raise ValueError("Iniciá el seguimiento antes de consultar esta fuente.")
            await self.radar.execute(JobCommand(job_id, "run_now"))

    async def theme(self):
        return await self.store.desktop_setting("theme") or "light"

    async def set_theme(self, name):
        if name not in {"light", "dark"}:
            raise ValueError("Elegí tema claro u oscuro.")
        await self.store.set_desktop_setting("theme", name)

    async def probe(self, job_id):
        async with self.guard:
            if self.worker:
                raise ValueError("Detené el seguimiento para consultar esta fuente por separado.")
            return await Radar(self.store, self.connectors).run_once(job_id)
