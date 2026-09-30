"""Aspects: concerns written once, mounted in the block of every builder offering them."""

from ..core.feature import Aspect
from . import statistics

ASPECTS: tuple[Aspect, ...] = (statistics.ASPECT,)
