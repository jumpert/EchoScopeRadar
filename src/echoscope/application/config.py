import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from echoscope.domain.models import Severity
from echoscope.domain.rules import Rule


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Credential(StrictModel):
    kind: Literal["bearer", "api_key", "oauth"]
    env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")

    def resolve(self) -> str | None:
        return os.environ.get(self.env) or None


class Source(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    type: str
    label: str | None = Field(default=None, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
    credential: Credential | None = None
    retention_days: int = Field(default=30, ge=1, le=30)


class Job(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    source: str
    enabled: bool = True
    interval_s: float = Field(default=60, ge=0.05, le=86400)
    timeout_s: float = Field(default=15, ge=0.05, le=300)
    rule_set: str
    relevant_only: bool = False


class RuleSpec(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    phrase: str = Field(min_length=1, max_length=256)
    severity: Literal["info", "important", "critical"] = "info"
    priority: int = 0
    case_sensitive: bool = False
    accent_sensitive: bool = False
    exclusions: list[str] = Field(default_factory=list, max_length=30)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    detect_variants: bool = False

    def compile(self) -> Rule:
        return Rule(
            self.id,
            self.phrase,
            Severity(self.severity),
            self.priority,
            self.case_sensitive,
            self.accent_sensitive,
            tuple(self.exclusions),
            tuple(self.aliases),
            self.detect_variants,
        )


class Configuration(StrictModel):
    version: Literal[1]
    sources: list[Source] = Field(max_length=100)
    jobs: list[Job] = Field(max_length=100)
    rule_sets: dict[str, list[RuleSpec]]
    desktop_profile: Literal[1] | None = None

    @model_validator(mode="after")
    def references(self):
        sources = {source.id for source in self.sources}
        if len(sources) != len(self.sources) or len({job.id for job in self.jobs}) != len(
            self.jobs
        ):
            raise ValueError("Los IDs de fuente y tarea deben ser únicos")
        for job in self.jobs:
            if job.source not in sources or job.rule_set not in self.rule_sets:
                raise ValueError(f"Fuente o conjunto de reglas desconocido para {job.id}")
        for rules in self.rule_sets.values():
            if len(rules) > 100 or len({rule.id for rule in rules}) != len(rules):
                raise ValueError("Cada conjunto admite hasta 100 reglas con IDs únicos")
            if any(
                not phrase.strip() or len(phrase) > 256
                for rule in rules
                for phrase in (*rule.exclusions, *rule.aliases)
            ):
                raise ValueError("Las variantes y exclusiones deben tener entre 1 y 256 caracteres")
        return self


class UniqueKeysLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError("Las claves de YAML deben ser texto")
            if key in mapping:
                raise ValueError("Clave duplicada en YAML")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def read_config(path: Path) -> Configuration:
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("El archivo YAML supera 1 MiB")
    return Configuration.model_validate(
        yaml.load(path.read_text(encoding="utf-8-sig"), Loader=UniqueKeysLoader)
    )
