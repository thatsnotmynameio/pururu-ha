"""sharding.py: PURURU_SHARD=i/N keeps one of N stable sets of whole test files."""

import pytest

import sharding

TEN = [("test_a.py", 40), ("test_b.py", 3), ("test_c.py", 17), ("test_d.py", 17),
       ("test_e.py", 1), ("test_f.py", 25), ("test_g.py", 8), ("test_h.py", 12),
       ("test_i.py", 5), ("test_j.py", 30)]


def test_three_shards_cover_every_file_once() -> None:
    """Ten files of varied counts in three shards: their union is every file, no file twice."""
    shards = [sharding.split(TEN, i, 3) for i in (1, 2, 3)]
    assert sorted(f for shard in shards for f in shard) == sorted(f for f, _ in TEN)
    assert all(shard for shard in shards)


def test_one_shard_is_every_file() -> None:
    """N=1 keeps every file."""
    assert sorted(sharding.split(TEN, 1, 1)) == sorted(f for f, _ in TEN)


def test_a_file_heavier_than_the_rest_is_alone() -> None:
    """The largest file, outweighing the others together, takes a bin alone."""
    files = [("test_big.py", 100), ("test_x.py", 10), ("test_y.py", 20), ("test_z.py", 5)]
    shards = [sharding.split(files, i, 2) for i in (1, 2)]
    assert ["test_big.py"] in shards


def test_the_order_given_does_not_change_the_shards() -> None:
    """Every xdist worker must keep the same files, whatever order it collected them in."""
    for i in (1, 2, 3):
        assert sorted(sharding.split(TEN, i, 3)) == sorted(sharding.split(TEN[::-1], i, 3))


def test_equal_counts_are_ordered_by_name() -> None:
    """Ties go by file name, so the same counts always land in the same bins."""
    files = [("test_b.py", 5), ("test_a.py", 5)]
    assert sharding.split(files, 1, 2) == ["test_a.py"]
    assert sharding.split(files, 2, 2) == ["test_b.py"]


@pytest.mark.parametrize(("value", "expected"), [("1/3", (1, 3)), ("3/3", (3, 3)), ("1/1", (1, 1))])
def test_a_shard_is_read(value: str, expected: tuple[int, int]) -> None:
    """i/N, 1-based."""
    assert sharding.parse(value) == expected


@pytest.mark.parametrize("value", ["0/3", "4/3", "a/b", "1", "1/0", "-1/3", "1/3/3", ""])
def test_a_wrong_shard_is_refused(value: str) -> None:
    """A malformed value, or i outside 1..N, is a usage error naming the expected form."""
    with pytest.raises(pytest.UsageError, match=r"PURURU_SHARD=i/N"):
        sharding.parse(value)
