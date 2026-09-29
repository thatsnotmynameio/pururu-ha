"""The translations' common texts, in HA's language with English for what it lacks."""

from collections.abc import Mapping

from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN

# Default texts, by their key in the translations' common block
type Texts = Mapping[str, str]
FALLBACK_LANGUAGE = "en"


async def async_texts(hass: HomeAssistant) -> Texts:
    """The common texts in HA's language; English for what it lacks."""
    prefix = f"component.{DOMAIN}.common."
    english = await async_get_translations(hass, FALLBACK_LANGUAGE, "common", [DOMAIN])
    local = await async_get_translations(hass, hass.config.language, "common", [DOMAIN])
    return {
        key.removeprefix(prefix): local.get(key) or text
        for key, text in english.items()
        if key.startswith(prefix)
    }
