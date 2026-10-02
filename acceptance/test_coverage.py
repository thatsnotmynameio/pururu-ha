"""The guard: the reference house covers everything pururu publishes, as Home Assistant shows it.

What must be covered is read only from what pururu publishes: its feature pages,
the docs' table of aspects, and the ready-made alerts and notifications its
shipped translations name. Covered means pururu created something for it, found
by the documented `reference` attribute, or by the documented ID of an
automation or script; the YAML alone proves nothing.
"""

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from typing import Any

from homeassistant.helpers import entity_registry as er

from steps import Home

REPO = Path(__file__).resolve().parents[1]
FEATURES = REPO / "docs/features"
ASPECTS = REPO / "docs/concepts/devices-and-features.mdx"
TRANSLATIONS = REPO / "custom_components/pururu/translations/en.json"
ALERT = re.compile(r"(\w+?)_alert_(\w+)")
NOTIFICATION = re.compile(r"(\w+?)_notification_(\w+)_name")


@dataclass(frozen=True)
class Published:
    """What pururu says it has: (namespace, name) for the ready-made alerts and notifications."""

    features: frozenset[str]
    device_keys: frozenset[str]
    aspects: frozenset[str]
    alerts: frozenset[tuple[str, str]]
    notifications: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class Created:
    """What Home Assistant holds from pururu: entities by their reference's `inside`, and generated IDs."""

    references: dict[str, str]
    generated: frozenset[str]


def aspects_table(page: str) -> tuple[set[str], set[str]]:
    """The device keys and the aspects the docs' table of aspects lists."""
    section = page.split("## Aspects\n", 1)[1].split("\n## ", 1)[0]
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in section.splitlines() if line.startswith("|")]
    header, body = rows[0], rows[2:]
    aspects = {cell.strip("`") for cell in header[2:]}
    device_keys = {re.search(r"`(\w+)`", row[0])[1] for row in body  # type: ignore[index]
                   if row[1] == "device key"}
    return device_keys, aspects


def published(feature_pages: list[str], aspects_page: str, translations: dict[str, Any]) -> Published:
    device_keys, aspects = aspects_table(aspects_page)
    return Published(
        features=frozenset(feature_pages),
        device_keys=frozenset(device_keys),
        aspects=frozenset(aspects),
        alerts=frozenset(found.groups() for key in translations["entity"]["binary_sensor"]
                         if (found := ALERT.fullmatch(key))),
        notifications=frozenset(found.groups() for key in translations["common"]
                                if (found := NOTIFICATION.fullmatch(key))))


def published_now() -> Published:
    return published([page.stem for page in FEATURES.glob("*.mdx")],
                     ASPECTS.read_text(encoding="utf-8"),
                     json.loads(TRANSLATIONS.read_text(encoding="utf-8")))


def created(home: Home) -> Created:
    references = {state.entity_id: reference["inside"]
                  for state in home.hass.states.async_all()
                  if isinstance(reference := state.attributes.get("reference"), dict)}
    generated = frozenset(state.entity_id for state in home.hass.states.async_all(("automation", "script"))
                          if state.entity_id.split(".", 1)[1].startswith("pururu_"))
    return Created(references, generated)


def aspect_in(path: list[str], aspect: str) -> bool:
    """Whether a reference's path sits in `aspect` (detected programs: `<feature>.programs.detected`)."""
    if aspect == "programs":
        return path[1:3] == ["programs", "detected"]
    return aspect in path[1:]


def missing(what: Published, house: Created) -> list[str]:
    """Each published item the house doesn't cover, named."""
    paths = [(entity_id, inside.split(".")) for entity_id, inside in house.references.items()]
    firsts = {path[0] for _, path in paths}
    gaps = [f"feature {key}" for key in sorted(what.features - firsts)]
    gaps += [f"device key {key}" for key in sorted(what.device_keys - firsts)]
    gaps += [f"aspect {aspect}" for aspect in sorted(what.aspects)
             if not any(aspect_in(path, aspect) for _, path in paths)
             and not (aspect == "notifications" and any("_notification_" in i for i in house.generated))]
    gaps += [f"{namespace} alert {name}" for namespace, name in sorted(what.alerts)
             if not any(entity_id.endswith(f"_{namespace}_alert_{name}") and path[1:] == ["alerts", name]
                        for entity_id, path in paths)]
    gaps += [f"{namespace} notification {name}" for namespace, name in sorted(what.notifications)
             if not any(generated.startswith("automation.")
                        and generated.endswith(f"_{namespace}_notification_{name}")
                        for generated in house.generated)]
    return gaps


async def test_the_house_covers_everything_published(house: Home) -> None:
    assert missing(published_now(), created(house)) == []


async def test_a_feature_without_a_place_is_named(house: Home) -> None:
    """AE1: a feature page `pump` the house has no place for."""
    now = published_now()
    assert missing(replace(now, features=now.features | {"pump"}), created(house)) == ["feature pump"]


async def test_a_ready_made_alert_not_enabled_is_named(house: Home) -> None:
    """AE2: the translations name a door alert `stuck` the house doesn't enable."""
    now = published_now()
    assert missing(replace(now, alerts=now.alerts | {("door", "stuck")}), created(house)) == [
        "door alert stuck"]


async def test_an_aspect_no_device_uses_is_named(house: Home) -> None:
    now = published_now()
    assert missing(replace(now, aspects=now.aspects | {"forecast"}), created(house)) == [
        "aspect forecast"]


def test_the_published_sources_are_read() -> None:
    now = published_now()
    assert {"appliance", "door", "window", "lights", "switches", "buttons"} <= now.features
    assert now.device_keys == {"programs", "reactions", "alerts"}
    assert now.aspects == {"alerts", "notifications", "statistics", "programs"}
    assert ("door", "no_opening") in now.alerts
    assert ("appliance", "finished") in now.notifications


async def test_a_feature_written_but_not_created_is_missing(home: Home) -> None:
    """R10: the YAML has lights, but their only ID is another integration's, so none is created."""
    home.hass.states.async_set("light.porch_lamp", "off")
    er.async_get(home.hass).async_get_or_create(
        "light", "other", "lamp", suggested_object_id="pururu_porch_light_lamp")
    assert await home.setup({"devices": {"porch": {"name": "Porch", "lights": {
        "lamp": {"entity": "homeassistant.light.porch_lamp", "name": "Lamp"}}}}})
    assert "feature lights" in missing(published_now(), created(home))
