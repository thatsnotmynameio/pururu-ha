"""Aspects: concerns written once, mounted in the block of every builder offering them."""

from ..core.feature import Aspect
from . import alerts, notifications, programs, statistics

# In build order: a builder's ready-made alerts, its detected programs, then
# its meters (after every total they meter, which seeds them), then its
# ready-made notifications (no entity: automations). Mounting doesn't follow
# it: catalogue.mount takes the deepest places first
ASPECTS: tuple[Aspect, ...] = (
    alerts.ASPECT,
    programs.ASPECT,
    statistics.ASPECT,
    notifications.ASPECT,
)
