"""Ready-made notifications: a made-up washer tells when its cycle finishes."""

from collections.abc import AsyncIterator
from pathlib import Path
import re
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from helpers import fake, generated, module, reload, setup, tick

KEY = "washer"
POWER = "sensor.demo_plug_power"
PHONE = "notify.phone"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}


def devices(notifications: Any, **device: Any) -> dict[str, Any]:
    """The washer, its appliance's ready-made notifications as given."""
    return {KEY: {"name": "Máquina", "appliance": {**APPLIANCE, "notifications": notifications}, **device}}


# --- configuration ------------------------------------------------------------------------


@pytest.mark.parametrize("notifications", [
    pytest.param({"finished": None}, id="null is every default"),
    pytest.param({"finished": {}}, id="empty is every default"),
    pytest.param({"finished": {"message": "Roupa pronta!", "notify": "notify.tablet"}}, id="all set"),
])
async def test_valid_notifications_are_accepted(ha: HomeAssistant, notifications: Any) -> None:
    assert await setup(ha, devices(notifications), config={"notify": PHONE})


@pytest.mark.parametrize(("notifications", "reason"), [
    pytest.param({"nope": None}, "nope is not a ready-made notification of appliance: finished",
                 id="unknown name"),
    pytest.param({"finished": {"lasts": 1}},
                 "'lasts' is an invalid option for 'pururu', check: "
                 "pururu->devices->washer->appliance->notifications->finished->lasts", id="unknown setting"),
    pytest.param({"finished": {"message": ""}}, "length of value must be at least 1", id="blank message"),
    pytest.param({"finished": {"notify": "phone"}}, "a notify action is notify.<name>",
                 id="not a notify action"),
    pytest.param({}, "length of value must be at least 1", id="empty"),
])
async def test_invalid_notifications_are_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                                 notifications: Any, reason: str) -> None:
    assert not await setup(ha, devices(notifications), config={"notify": PHONE})
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(reason in message for message in errors), errors


async def test_a_feature_offering_none_takes_no_notifications(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    config = {KEY: {"name": "Porta", "door": {"contact": "binary_sensor.x",
                                              "notifications": {"finished": None}}}}
    assert not await setup(ha, config, config={"notify": PHONE})
    assert "'notifications' is an invalid option" in caplog.text


async def test_the_device_has_no_notifications_key(ha: HomeAssistant,
                                                   caplog: pytest.LogCaptureFixture) -> None:
    """They're in their feature's block, as its ready-made alerts."""
    config = {KEY: {"name": "Máquina", "appliance": APPLIANCE,
                    "notifications": {"appliance": {"finished": None}}}}
    assert not await setup(ha, config, config={"notify": PHONE})
    assert "'notifications' is an invalid option" in caplog.text


async def test_a_notification_needs_somewhere_to_go(ha: HomeAssistant,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, devices({"finished": None}))
    assert ("device washer: appliance: notifications: finished needs notify, here or in config.notify"
            in caplog.text)


async def test_its_own_notify_is_enough(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"finished": {"notify": PHONE}}))


async def test_a_notification_and_a_reaction_with_one_id_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """a's reaction x_appliance_notification_finished and a_reaction_x's finished: one automation ID."""
    door = {"name": "Porta", "entity": "binary_sensor.door", "to": "on"}
    config = {
        "a": {"name": "A", "appliance": APPLIANCE, "reactions": {"x_appliance_notification_finished": door}},
        "a_reaction_x": {"name": "B", "appliance": {**APPLIANCE, "power": "sensor.other",
                                                    "notifications": {"finished": None}}},
    }
    assert not await setup(ha, config, config={"notify": PHONE})
    assert ("device a_reaction_x: automation.pururu_a_reaction_x_appliance_notification_finished "
            "is already a reaction of device a") in caplog.text


RUNNING = "binary_sensor.pururu_washer_appliance_running"
FINISHED = "automation.pururu_washer_appliance_notification_finished"
ENABLED = {"finished": None}


# --- the automation -----------------------------------------------------------------------


async def test_the_file_holds_the_notifications_automation(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    assert generated(ha) == [{
        "id": "pururu_washer_appliance_notification_finished",
        "alias": "Máquina Finished",
        "description": "pururu: washer, appliance notification finished",
        "triggers": [{"trigger": "state", "entity_id": RUNNING, "from": "on", "to": "off"}],
        "actions": [{"parallel": [{"action": PHONE, "data": {"title": "Máquina", "message": "The cycle finished."},
                                   "continue_on_error": True}]}],
    }]


async def test_in_hass_language(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    [automation] = generated(ha)
    assert automation["alias"] == "Máquina Terminou"
    assert automation["actions"][0]["parallel"][0]["data"]["message"] == "O ciclo terminou."


async def test_its_own_message_and_notify(ha: HomeAssistant) -> None:
    mine = {"finished": {"message": "Roupa {pronta}!", "notify": ["notify.a", "notify.b"]}}
    assert await setup(ha, devices(mine), config={"notify": PHONE})
    [automation] = generated(ha)
    told = automation["actions"][0]["parallel"]
    assert [action["action"] for action in told] == ["notify.a", "notify.b"]
    assert told[0]["data"]["message"] == "{% raw %}Roupa {pronta}!{% endraw %}"


async def test_it_follows_a_renamed_running(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    er.async_get(ha).async_update_entity(RUNNING, new_entity_id="binary_sensor.washer_running")
    await ha.async_block_till_done()
    assert generated(ha)[0]["triggers"][0]["entity_id"] == "binary_sensor.washer_running"


async def test_not_generated_when_running_is_not_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    ha.states.async_set(RUNNING, "off")  # another integration's entity holds the ID
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    assert generated(ha) == []
    assert (f"{FINISHED} follows {RUNNING}, which is not created; not generating it") in caplog.text


async def test_dropped_from_the_yaml_it_goes(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    await reload(ha, {KEY: {"name": "Máquina", "appliance": APPLIANCE}}, config={"notify": PHONE})
    assert generated(ha) == []


# --- told -----------------------------------------------------------------------------------


@pytest.fixture
async def automations(ha: HomeAssistant) -> AsyncIterator[None]:
    """HA's automations, from a configuration.yaml whose include merges pururu's file."""
    def both(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"automation pururu": generated(ha)}
    with patch("homeassistant.config.load_yaml_config_file", side_effect=both):
        assert await async_setup_component(ha, "automation", both())
        yield


async def cycle(ha: HomeAssistant, freezer: Any) -> None:
    """A washing cycle: running on after on_delay, off after off_delay."""
    await fake(ha, POWER, "100")
    await tick(ha, freezer, 60)
    assert ha.states.get(RUNNING).state == "on"
    await fake(ha, POWER, "0")
    await tick(ha, freezer, 120)
    assert ha.states.get(RUNNING).state == "off"
    await ha.async_block_till_done()


async def test_the_phone_is_told_when_a_cycle_finishes(ha: HomeAssistant, freezer: Any,
                                                       automations: None) -> None:
    calls = async_mock_service(ha, "notify", "phone")
    await fake(ha, POWER, "0")
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    await cycle(ha, freezer)
    assert [call.data for call in calls] == [{"title": "Máquina", "message": "The cycle finished."}]


async def test_a_reload_while_idle_tells_nobody(ha: HomeAssistant, freezer: Any,
                                               automations: None) -> None:
    """A reload takes running away and brings it back off: no cycle ended."""
    calls = async_mock_service(ha, "notify", "phone")
    await fake(ha, POWER, "0")
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    assert ha.states.get(RUNNING).state == "off"
    await reload(ha, devices(ENABLED), config={"notify": PHONE})
    await tick(ha, freezer, 180)
    assert ha.states.get(RUNNING).state == "off"
    assert calls == []


async def test_a_reload_tells_nobody(ha: HomeAssistant, freezer: Any, automations: None) -> None:
    calls = async_mock_service(ha, "notify", "phone")
    await fake(ha, POWER, "100")
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    await tick(ha, freezer, 60)
    await reload(ha, devices(ENABLED), config={"notify": PHONE})
    await tick(ha, freezer, 60)
    assert calls == []


async def test_the_automation_has_the_pururu_entity_id(ha: HomeAssistant, automations: None) -> None:
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    state = ha.states.get(FINISHED)
    assert state is not None
    assert state.attributes["friendly_name"] == "Máquina Finished"


async def test_a_repair_while_the_file_is_not_loaded(ha: HomeAssistant, freezer: Any) -> None:
    """A configuration.yaml without the include: the notification isn't loaded."""
    with patch("homeassistant.config.load_yaml_config_file", side_effect=lambda *_a, **_k: {}):
        assert await async_setup_component(ha, "automation", {})
        assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    await tick(ha, freezer, 5)
    issue = ir.async_get(ha).async_get_issue("pururu", "automations_not_included")
    assert issue is not None
    assert issue.translation_placeholders == {
        "include": "automation pururu: !include_dir_merge_list pururu/automations",
        "file": "pururu/automations/automations.yaml",
    }


DOOR = {"name": "Porta", "entity": "binary_sensor.door", "to": "on"}


async def test_reactions_and_notifications_share_one_file(ha: HomeAssistant) -> None:
    """One automations kind: the reactions' then the notifications', tracked under one data key."""
    assert await setup(ha, devices(ENABLED, reactions={"door": DOOR}), config={"notify": PHONE})
    both = ["pururu_washer_reaction_door", "pururu_washer_appliance_notification_finished"]
    assert [automation["id"] for automation in generated(ha)] == both
    [entry] = ha.config_entries.async_entries("pururu")
    assert entry.data["automations"] == both


REACTION = "pururu_washer_reaction_door"
NOTIFICATION = "pururu_washer_appliance_notification_finished"


@pytest.mark.parametrize(("kept", "dropped", "device"), [
    pytest.param(REACTION, NOTIFICATION, {"name": "Máquina", "appliance": APPLIANCE, "reactions": {"door": DOOR}},
                 id="the notification dropped"),
    pytest.param(NOTIFICATION, REACTION, devices(ENABLED)[KEY], id="the reaction dropped"),
])
async def test_dropping_one_source_keeps_the_others(ha: HomeAssistant, automations: None,
                                                   kept: str, dropped: str, device: dict[str, Any]) -> None:
    """One tracked list for both: what goes is the dropped one's, never the other's."""
    assert await setup(ha, devices(ENABLED, reactions={"door": DOOR}), config={"notify": PHONE})
    await reload(ha, {KEY: device}, config={"notify": PHONE})
    assert [automation["id"] for automation in generated(ha)] == [kept]
    [entry] = ha.config_entries.async_entries("pururu")
    assert entry.data["automations"] == [kept]
    registry = er.async_get(ha)
    assert registry.async_get_entity_id("automation", "automation", dropped) is None
    assert registry.async_get_entity_id("automation", "automation", kept) == f"automation.{kept}"


async def test_one_repair_for_reactions_and_notifications(ha: HomeAssistant, freezer: Any) -> None:
    """Not included, the reactions' and the notifications' automations raise one issue: one include."""
    with patch("homeassistant.config.load_yaml_config_file", side_effect=lambda *_a, **_k: {}):
        assert await async_setup_component(ha, "automation", {})
        assert await setup(ha, devices(ENABLED, reactions={"door": DOOR}), config={"notify": PHONE})
    await tick(ha, freezer, 5)
    issues = [issue_id for domain, issue_id in ir.async_get(ha).issues if domain == "pururu"]
    assert issues == ["automations_not_included"]


async def test_removing_the_entry_empties_the_file(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    entry = ha.config_entries.async_entries("pururu")[0]
    await ha.config_entries.async_remove(entry.entry_id)
    await ha.async_block_till_done()
    assert generated(ha) == []


# --- the docs ----------------------------------------------------------------------------

PAGE = Path(__file__).resolve().parents[1] / "docs/concepts/notifications.mdx"


def test_the_page_lists_every_ready_made_notification(ha: HomeAssistant) -> None:
    page = PAGE.read_text(encoding="utf-8")
    section = re.search(r"## Ready-made notifications\n(.*?)\n## ", page, re.DOTALL)
    assert section is not None, "no Ready-made notifications section"
    for name, feature in module("features").FEATURES.items():
        for notification in module("core.feature").happenings_of(feature):
            assert f"`{name}: notifications: {notification}`" in section[1], notification
