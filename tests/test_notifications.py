"""Ready-made notifications: a made-up washer tells when its cycle finishes."""

from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from helpers import setup

KEY = "washer"
POWER = "sensor.demo_plug_power"
PHONE = "notify.phone"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}


def devices(notifications: Any, **device: Any) -> dict[str, Any]:
    return {KEY: {"name": "Máquina", "appliance": APPLIANCE, "notifications": notifications, **device}}


# --- configuration ------------------------------------------------------------------------


@pytest.mark.parametrize("notifications", [
    pytest.param({"appliance": {"finished": None}}, id="null is every default"),
    pytest.param({"appliance": {"finished": {}}}, id="empty is every default"),
    pytest.param({"appliance": {"finished": {"message": "Roupa pronta!", "notify": "notify.tablet"}}},
                 id="all set"),
])
async def test_valid_notifications_are_accepted(ha: HomeAssistant, notifications: Any) -> None:
    assert await setup(ha, devices(notifications), config={"notify": PHONE})


@pytest.mark.parametrize(("notifications", "reason"), [
    pytest.param({"nope": {"finished": None}}, "nope is not a feature", id="not a feature"),
    pytest.param({"switches": {"on": None}}, "switches offers no ready-made notification",
                 id="a feature offering none"),
    pytest.param({"appliance": {"nope": None}},
                 "appliance: nope is not a ready-made notification of appliance: finished", id="unknown name"),
    pytest.param({"appliance": {"finished": {"lasts": 1}}}, "'lasts' is an invalid option", id="unknown setting"),
    pytest.param({"appliance": {"finished": {"message": ""}}}, "length of value must be at least 1",
                 id="blank message"),
    pytest.param({"appliance": {}}, "length of value must be at least 1", id="no name"),
    pytest.param({}, "length of value must be at least 1", id="empty"),
])
async def test_invalid_notifications_are_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                                 notifications: Any, reason: str) -> None:
    assert not await setup(ha, devices(notifications), config={"notify": PHONE})
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(reason in message for message in errors), errors


async def test_a_feature_the_device_lacks_is_refused(ha: HomeAssistant,
                                                     caplog: pytest.LogCaptureFixture) -> None:
    config = {KEY: {"name": "Máquina", "switches": {"x": {"entity": "switch.x", "name": "X"}},
                    "notifications": {"appliance": {"finished": None}}}}
    assert not await setup(ha, config, config={"notify": PHONE})
    assert "notifications: appliance: the device has no appliance" in caplog.text


async def test_a_notification_needs_somewhere_to_go(ha: HomeAssistant,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, devices({"appliance": {"finished": None}}))
    assert ("device washer: notifications: appliance: finished needs notify, here or in config.notify"
            in caplog.text)


async def test_its_own_notify_is_enough(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"appliance": {"finished": {"notify": PHONE}}}))


async def test_notifications_alone_are_not_a_feature(ha: HomeAssistant,
                                                     caplog: pytest.LogCaptureFixture) -> None:
    config = {KEY: {"name": "Máquina", "notifications": {"appliance": {"finished": None}}}}
    assert not await setup(ha, config, config={"notify": PHONE})


async def test_a_notification_and_a_reaction_with_one_id_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """a's reaction appliance_notification_finished and a_reaction's notification: one automation ID."""
    door = {"name": "Porta", "entity": "binary_sensor.door", "to": "on"}
    config = {
        "a": {"name": "A", "appliance": APPLIANCE, "reactions": {"x_appliance_notification_finished": door}},
        "a_reaction_x": {"name": "B", "appliance": {**APPLIANCE, "power": "sensor.other"},
                         "notifications": {"appliance": {"finished": None}}},
    }
    assert not await setup(ha, config, config={"notify": PHONE})
    assert ("device a_reaction_x: automation.pururu_a_reaction_x_appliance_notification_finished "
            "is already a reaction of device a") in caplog.text
