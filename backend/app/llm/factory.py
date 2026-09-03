"""Chooses which Brain the pipeline talks to.

Selection order:

1. The provider the user picked in Settings, if its API key has been pushed to
   this process by the desktop vault.
2. The deterministic demo Brain.

Live calls that fail are reported to the caller, which decides whether to fall
back. Nothing here raises during selection, so a missing or broken provider can
never stop an assignment from being processed.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from .. import credentials
from ..models import ModelRoute, ProviderConfiguration
from ..llm.mock import DemoBrainProvider
from ..llm.providers import BrainError, RemoteBrainProvider, SUPPORTED_PROVIDERS, build_provider

logger = logging.getLogger(__name__)

# Providers created only as demo scaffolding; never dialled over the network.
_PLACEHOLDER_PROVIDERS = {"demo-brain", "zai-computer-use"}


def active_configuration(session: Session) -> ProviderConfiguration | None:
    """The provider configuration the Brain routes currently point at."""
    route = session.exec(select(ModelRoute).order_by(ModelRoute.id.desc())).first()
    if route:
        configuration = session.get(ProviderConfiguration, route.provider_configuration_id)
        if configuration and configuration.provider in SUPPORTED_PROVIDERS:
            return configuration
    # Fall back to any supported configuration, most recently written first.
    for configuration in session.exec(select(ProviderConfiguration).order_by(ProviderConfiguration.id.desc())).all():
        if configuration.provider in SUPPORTED_PROVIDERS and configuration.provider not in _PLACEHOLDER_PROVIDERS:
            return configuration
    return None


def get_brain(session: Session) -> DemoBrainProvider | RemoteBrainProvider:
    """The Brain to use for this request, live if one is configured and keyed."""
    configuration = active_configuration(session)
    if not configuration:
        return DemoBrainProvider()

    api_key = credentials.get_key(configuration.provider)
    if not api_key:
        # Configured but the key has not been pushed from the vault this run.
        return DemoBrainProvider()

    try:
        return build_provider(configuration.provider, configuration.model, api_key, configuration.base_url)
    except BrainError as error:
        logger.warning("Falling back to the demo Brain: %s", error)
        return DemoBrainProvider()


def brain_status(session: Session) -> dict:
    """What the UI shows about the Brain: configured provider, model, and whether it is live."""
    configuration = active_configuration(session)
    if not configuration:
        return {"provider": None, "model": None, "live": False, "reason": "No Brain provider selected yet."}
    if not credentials.has_key(configuration.provider):
        return {
            "provider": configuration.provider,
            "model": configuration.model,
            "live": False,
            "reason": "No API key is available for this provider in the desktop vault.",
        }
    return {"provider": configuration.provider, "model": configuration.model, "live": True, "reason": None}
