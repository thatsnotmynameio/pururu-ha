"""Messages: the notify actions they go to, and their text as HA shows it.

A reaction's message and a ready-made notification are told through HA's
notify actions, from the automations pururu generates. Their text is the
user's, never a template.
"""

from collections.abc import Sequence
import re
from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from .resolve import HOME_ASSISTANT

_ACTION = re.compile(rf"{HOME_ASSISTANT}\.(notify\.[a-z0-9_]+)")


def action(value: Any) -> str:
    """A notify action, Home Assistant's: homeassistant.notify.<name>; the action alone (notify.<name>).

    As mobile_app's homeassistant.notify.mobile_app_<phone>. The generated
    automations call it as Home Assistant names it; a refusal quotes what the
    author wrote.
    """
    text = cv.string(value)
    if (found := _ACTION.fullmatch(text)) is None:
        raise vol.Invalid(
            f"{text} is not a notify action: {HOME_ASSISTANT}.notify.<name>"
        )
    return found[1]


# config: notify, and a reaction's or a notification's own: one or a list
TARGETS = vol.All(cv.ensure_list, vol.Length(min=1), [action])


def escaped(text: str) -> str:
    """`text` as HA's templates show it: every template delimiter starts with {.

    In a raw block, as Alert2's own jinja2Escape does: each {% in the text
    (an {% endraw %} would end the block) leaves it, is written as a string,
    and opens it again.
    """
    if "{" not in text:
        return text
    kept = text.replace("{%", '{% endraw %}{{ "{%" }}{% raw %}')
    return f"{{% raw %}}{kept}{{% endraw %}}"


def actions(targets: Sequence[str], title: str, message: str) -> list[dict[str, Any]]:
    """Tell each target the title and the message; one failing doesn't keep another from being told.

    In parallel: a sequence stops at an action that doesn't exist (a phone
    unpaired), whatever continue_on_error says; parallel runs every branch.
    """
    data = {"title": escaped(title), "message": escaped(message)}
    return [
        {
            "parallel": [
                {"action": target, "data": dict(data), "continue_on_error": True}
                for target in targets
            ]
        }
    ]
