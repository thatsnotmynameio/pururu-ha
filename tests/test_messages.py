"""Messages: where they go (notify actions) and how they are written (text, never a template)."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
import pytest
import voluptuous as vol

from helpers import module


@pytest.mark.parametrize(("value", "expected"), [
    pytest.param("notify.mobile_app_phone", ["notify.mobile_app_phone"], id="one"),
    pytest.param(["notify.a", "notify.b"], ["notify.a", "notify.b"], id="a list"),
])
def test_targets_are_a_list_of_notify_actions(ha: HomeAssistant, value: Any, expected: list[str]) -> None:
    assert module("messages").TARGETS(value) == expected


@pytest.mark.parametrize("value", [
    pytest.param("mobile_app_phone", id="no domain"),
    pytest.param("script.phone", id="another domain"),
    pytest.param("notify.Phone", id="not a slug"),
    pytest.param("notify.", id="no name"),
    pytest.param([], id="none"),
    pytest.param(None, id="null"),
])
def test_anything_else_is_refused(ha: HomeAssistant, value: Any) -> None:
    with pytest.raises(vol.Invalid):
        module("messages").TARGETS(value)


@pytest.mark.parametrize("text", [
    "A máquina terminou.", "Roupa {pronta}", "{{ states('x') }}", "{% raw %}", "{% endraw %}", "a {% b",
])
def test_escaped_text_renders_as_written(ha: HomeAssistant, text: str) -> None:
    rendered = Template(module("messages").escaped(text), ha).async_render(parse_result=False)
    assert rendered == text


def test_text_without_a_brace_is_left_alone(ha: HomeAssistant) -> None:
    assert module("messages").escaped("A máquina terminou.") == "A máquina terminou."


def test_each_target_is_told_the_title_and_the_message(ha: HomeAssistant) -> None:
    assert module("messages").actions(["notify.a", "notify.b"], "Máquina", "Terminou {x}") == [
        {"action": "notify.a", "data": {"title": "Máquina", "message": "{% raw %}Terminou {x}{% endraw %}"},
         "continue_on_error": True},
        {"action": "notify.b", "data": {"title": "Máquina", "message": "{% raw %}Terminou {x}{% endraw %}"},
         "continue_on_error": True},
    ]
