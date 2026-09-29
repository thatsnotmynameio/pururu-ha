"""Messages: the notify actions they go to, and their text as HA shows it.

A reaction's message and a ready-made notification are told through HA's
notify actions, from the automations pururu generates. Their text is the
user's, never a template.
"""

from collections.abc import Sequence
from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

# A notify action: notify.<name>, as mobile_app's notify.mobile_app_<phone>
ACTION = vol.All(
    cv.string,
    vol.Match(r"^notify\.[a-z0-9_]+$", msg="a notify action is notify.<name>"),
)
# config: notify, and a reaction's or a notification's own: one or a list
TARGETS = vol.All(cv.ensure_list, vol.Length(min=1), [ACTION])


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
    """Tell each target the title and the message; one failing doesn't keep the next from being told."""
    data = {"title": escaped(title), "message": escaped(message)}
    return [
        {"action": target, "data": dict(data), "continue_on_error": True}
        for target in targets
    ]
