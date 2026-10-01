"""PURURU_SHARD=i/N: whole test files split into N stable bins, for CI's parallel test jobs."""

from collections.abc import Iterable

import pytest

USAGE = "PURURU_SHARD=i/N expected, with 1 <= i <= N (as 2/3), got {!r}"


def parse(value: str) -> tuple[int, int]:
    """(i, N) from i/N, 1-based; anything else, 0/3 or 4/3 too, a usage error."""
    i, slash, n = value.partition("/")
    if not (slash and i.isdecimal() and n.isdecimal() and 1 <= int(i) <= int(n)):
        raise pytest.UsageError(USAGE.format(value))
    return int(i), int(n)


def split(files: Iterable[tuple[str, int]], i: int, n: int) -> list[str]:
    """The files of bin i of n: largest item count first (ties by name), each to the lightest bin.

    Whatever order the files come in, every caller (every xdist worker) gets the same bins.
    """
    bins: list[list[str]] = [[] for _ in range(n)]
    weights = [0] * n
    for name, count in sorted(files, key=lambda file: (-file[1], file[0])):
        lightest = weights.index(min(weights))
        bins[lightest].append(name)
        weights[lightest] += count
    return bins[i - 1]
