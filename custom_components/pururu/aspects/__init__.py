"""Aspects: concerns written once, mounted in the block of every builder offering them."""

from ..core.feature import Aspect
from . import alerts, statistics

# In build order: a builder's ready-made alerts, then its meters
ASPECTS: tuple[Aspect, ...] = (alerts.ASPECT, statistics.ASPECT)
