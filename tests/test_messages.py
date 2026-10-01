"""Messages: where they go (notify actions) and how they are written (text, never a template)."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
import pytest
import voluptuous as vol

from helpers import module


@pytest.mark.parametrize(("value", "expected"), [
    pytest.param("homeassistant.notify.mobile_app_phone", ["notify.mobile_app_phone"], id="one"),
    pytest.param(["homeassistant.notify.a", "homeassistant.notify.b"], ["notify.a", "notify.b"], id="a list"),
])
def test_targets_are_a_list_of_notify_actions(ha: HomeAssistant, value: Any, expected: list[str]) -> None:
    assert module("core.messages").TARGETS(value) == expected


@pytest.mark.parametrize("value", [
    pytest.param("mobile_app_phone", id="no domain"),
    pytest.param("homeassistant.script.phone", id="another domain"),
    pytest.param("homeassistant.notify.Phone", id="not a slug"),
    pytest.param("homeassistant.notify.", id="no name"),
    pytest.param("notify.mobile_app_phone", id="without homeassistant, as before 0.2.2"),
    pytest.param([], id="none"),
    pytest.param(None, id="null"),
])
def test_anything_else_is_refused(ha: HomeAssistant, value: Any) -> None:
    targets = module("core.messages").TARGETS
    with pytest.raises(vol.Invalid):
        targets(value)


def test_a_refusal_quotes_what_was_written(ha: HomeAssistant) -> None:
    with pytest.raises(vol.Invalid, match=r"^notify\.mobile_app_phone is not a notify action: "
                       r"homeassistant\.notify\.<name>"):
        module("core.messages").action("notify.mobile_app_phone")


@pytest.mark.parametrize("text", [
    "A máquina terminou.", "Roupa {pronta}", "{{ states('x') }}", "{% raw %}", "{% endraw %}", "a {% b",
])
def test_escaped_text_renders_as_written(ha: HomeAssistant, text: str) -> None:
    rendered = Template(module("core.messages").escaped(text), ha).async_render(parse_result=False)
    assert rendered == text


def test_text_without_a_brace_is_left_alone(ha: HomeAssistant) -> None:
    assert module("core.messages").escaped("A máquina terminou.") == "A máquina terminou."


def test_each_target_is_told_the_title_and_the_message(ha: HomeAssistant) -> None:
    assert module("core.messages").actions(["notify.a", "notify.b"], "Máquina", "Terminou {x}") == [{"parallel": [
        {"action": "notify.a", "data": {"title": "Máquina", "message": "{% raw %}Terminou {x}{% endraw %}"},
         "continue_on_error": True},
        {"action": "notify.b", "data": {"title": "Máquina", "message": "{% raw %}Terminou {x}{% endraw %}"},
         "continue_on_error": True},
    ]}]
