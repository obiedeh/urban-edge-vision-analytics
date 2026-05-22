"""Exhaustive compatibility test over all 8 subsets of the 3 packs."""
from __future__ import annotations

import pytest

from packs.base import PackId
from packs.compatibility import (
    ALLOWED_SETS,
    IncompatiblePackSelection,
    validate_pack_set,
)

_ALL_PACKS = [PackId.moving_object, PackId.speed_violation, PackId.stop_sign]

# All 8 subsets of the 3 packs
_ALL_SUBSETS = [
    frozenset(),
    frozenset({PackId.moving_object}),
    frozenset({PackId.speed_violation}),
    frozenset({PackId.stop_sign}),
    frozenset({PackId.moving_object, PackId.speed_violation}),
    frozenset({PackId.moving_object, PackId.stop_sign}),
    frozenset({PackId.speed_violation, PackId.stop_sign}),           # blocked
    frozenset({PackId.moving_object, PackId.speed_violation, PackId.stop_sign}),  # blocked
]

_BLOCKED = {
    frozenset({PackId.speed_violation, PackId.stop_sign}),
    frozenset({PackId.moving_object, PackId.speed_violation, PackId.stop_sign}),
}


@pytest.mark.parametrize("subset", _ALL_SUBSETS)
def test_all_8_subsets(subset: frozenset[PackId]) -> None:
    """Exactly the 6 allowed sets pass; the 2 blocked sets raise."""
    if subset in _BLOCKED:
        with pytest.raises(IncompatiblePackSelection):
            validate_pack_set(subset)
    else:
        validate_pack_set(subset)  # must not raise


def test_allowed_sets_has_exactly_6_entries() -> None:
    assert len(ALLOWED_SETS) == 6


def test_blocked_speed_stop_error_message() -> None:
    with pytest.raises(IncompatiblePackSelection) as exc_info:
        validate_pack_set([PackId.speed_violation, PackId.stop_sign])
    err = exc_info.value
    assert frozenset({PackId.speed_violation, PackId.stop_sign}) == err.selected


def test_blocked_all_three_error_message() -> None:
    with pytest.raises(IncompatiblePackSelection) as exc_info:
        validate_pack_set(_ALL_PACKS)
    err = exc_info.value
    assert err.selected == frozenset(_ALL_PACKS)


def test_empty_set_allowed() -> None:
    validate_pack_set([])  # camera idle — allowed


def test_each_pack_alone_allowed() -> None:
    for pack in _ALL_PACKS:
        validate_pack_set([pack])


def test_allowed_sets_content() -> None:
    assert frozenset() in ALLOWED_SETS
    assert frozenset({PackId.moving_object}) in ALLOWED_SETS
    assert frozenset({PackId.speed_violation}) in ALLOWED_SETS
    assert frozenset({PackId.stop_sign}) in ALLOWED_SETS
    assert frozenset({PackId.moving_object, PackId.speed_violation}) in ALLOWED_SETS
    assert frozenset({PackId.moving_object, PackId.stop_sign}) in ALLOWED_SETS
    assert frozenset({PackId.speed_violation, PackId.stop_sign}) not in ALLOWED_SETS
    assert (
        frozenset({PackId.moving_object, PackId.speed_violation, PackId.stop_sign})
        not in ALLOWED_SETS
    )
