"""Ready-made notifications: what a device's features offer to tell, as automations pururu generates.

A device's `notifications` enables them, by feature and name: each is a
Happening of the feature (Feature.notifications), told once through HA's notify
actions (messages.py). Each becomes an automation in
pururu/automations/notifications.yaml, next to the reactions' in the folder
configuration.yaml includes (generated.py).
"""

from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from . import messages
from .const import CONF_MESSAGE, CONF_NOTIFICATIONS, CONF_NOTIFY, ENTITY_PREFIX
from .feature import TEXT, qualified
from .features import FEATURES
from .generated import Kind

# The namespace of a notification's automation ID, inside its feature's
NAMESPACE = "notification"
KIND = Kind(
    domain="automation",
    folder="pururu/automations",
    file="pururu/automations/notifications.yaml",
    merge="list",
    issue="notifications_not_included",
    data_key=CONF_NOTIFICATIONS,
    one="an automation",
    plural="automations",
    source="notifications",
)
# What one takes: its text, where it goes; a schema of its own, so unknown keys are refused
SETTINGS = vol.Schema(
    {vol.Optional(CONF_MESSAGE): TEXT, vol.Optional(CONF_NOTIFY): messages.TARGETS}
)
# feature key -> name -> settings (null: every default); schemas of their own:
# ALLOW_EXTRA would let a key that isn't a slug through
_BLOCK = vol.All(
    vol.Schema(
        {
            cv.slug: vol.All(
                vol.Schema({cv.slug: vol.Any(None, dict)}), vol.Length(min=1)
            )
        }
    ),
    vol.Length(min=1),
)


def validate(value: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """The device's `notifications`: every feature one that offers them, every name one it offers."""
    enabled: dict[str, dict[str, dict[str, Any]]] = {}
    for key, names in _BLOCK(value).items():
        if (feature := FEATURES.get(key)) is None:
            raise vol.Invalid(f"{key} is not a feature", path=[key])
        if not feature.notifications:
            raise vol.Invalid(f"{key} offers no ready-made notification", path=[key])
        offered = ", ".join(feature.notifications)
        enabled[key] = {}
        for name, settings in names.items():
            if name not in feature.notifications:
                raise vol.Invalid(
                    f"{key}: {name} is not a ready-made notification of {key}: {offered}",
                    path=[key, name],
                )
            enabled[key][name] = SETTINGS(settings or {})
    return enabled


def automation_id(device_key: str, namespace: str, name: str) -> str:
    """The automation's ID, and the object ID of its entity ID: the pururu pattern."""
    return f"{ENTITY_PREFIX}_{device_key}_{qualified(namespace, qualified(NAMESPACE, name))}"
