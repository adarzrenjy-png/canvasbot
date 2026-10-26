"""Loads `config/models.toml`: providers, role-to-model routing, and prices."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key_env: str


@dataclass(frozen=True)
class Role:
    name: str
    provider: str
    model: str
    reasoning_effort: str | None = None
    fallback_provider: str | None = None
    fallback_model: str | None = None


@dataclass(frozen=True)
class Price:
    input_per_mtok: float = 0.0
    cached_input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    per_image: float = 0.0
    per_audio_hour: float = 0.0


@dataclass(frozen=True)
class ModelConfig:
    providers: dict[str, Provider]
    roles: dict[str, Role]
    pricing: dict[str, Price] = field(default_factory=dict)

    def role(self, name: str) -> Role:
        try:
            return self.roles[name]
        except KeyError as error:
            raise KeyError(f"No model role named {name!r} in models.toml") from error

    def price(self, model: str) -> Price:
        # Unknown models are priced like the most expensive text model we know, so the
        # meter never under-counts.
        if model in self.pricing:
            return self.pricing[model]
        return max(self.pricing.values(), key=lambda p: p.output_per_mtok, default=Price())


def parse_model_config(data: dict[str, Any]) -> ModelConfig:
    providers = {
        name: Provider(
            name=name, base_url=raw["base_url"].rstrip("/"), api_key_env=raw["api_key_env"]
        )
        for name, raw in data.get("providers", {}).items()
    }
    roles = {name: Role(name=name, **raw) for name, raw in data.get("roles", {}).items()}
    pricing = {model: Price(**raw) for model, raw in data.get("pricing", {}).items()}
    for role in roles.values():
        for provider in (role.provider, role.fallback_provider):
            if provider is not None and provider not in providers:
                raise ValueError(f"Role {role.name!r} names unknown provider {provider!r}")
    return ModelConfig(providers=providers, roles=roles, pricing=pricing)


@lru_cache(maxsize=1)
def load_model_config() -> ModelConfig:
    text = resources.files("jig.config").joinpath("models.toml").read_text(encoding="utf-8")
    return parse_model_config(tomllib.loads(text))
