from __future__ import annotations

from collections.abc import Iterable

from .base import PackId

ALLOWED_SETS: set[frozenset[PackId]] = {
    frozenset(),
    frozenset({PackId.moving_object}),
    frozenset({PackId.speed_violation}),
    frozenset({PackId.stop_sign}),
    frozenset({PackId.moving_object, PackId.speed_violation}),
    frozenset({PackId.moving_object, PackId.stop_sign}),
}

# Human-readable reasons for blocked combinations
_BLOCK_REASON: dict[frozenset[PackId], str] = {
    frozenset({PackId.speed_violation, PackId.stop_sign}): (
        "Pack 2 (Speed) needs an oblique long sight-line with two calibration gates; "
        "Pack 3 (Stop Sign) needs a near-orthogonal view of a stop bar. "
        "A single camera cannot serve both without measurable degradation. "
        "Use two cameras for sites that need both."
    ),
    frozenset({PackId.moving_object, PackId.speed_violation, PackId.stop_sign}): (
        "Pack 2 and Pack 3 cannot share a camera (conflicting sight-line requirements). "
        "See §11.4 of the operator brief."
    ),
}


class IncompatiblePackSelection(ValueError):
    """Raised when a requested pack set violates the §11.4 compatibility rule."""

    def __init__(self, selected: frozenset[PackId]) -> None:
        self.selected = selected
        self.allowed = ALLOWED_SETS
        reason = _BLOCK_REASON.get(selected, "Pack combination is not allowed.")
        allowed_list = [sorted(str(p) for p in s) for s in ALLOWED_SETS]
        super().__init__(
            f"Incompatible pack selection {sorted(str(p) for p in selected)}: {reason} "
            f"Allowed sets: {allowed_list}"
        )


class MissingPrerequisite(ValueError):
    """Raised when a pack is selected but its required configuration is absent."""

    def __init__(self, pack_id: PackId, prerequisite: str) -> None:
        self.pack_id = pack_id
        self.prerequisite = prerequisite
        super().__init__(
            f"Pack '{pack_id}' requires '{prerequisite}' to be configured first."
        )


def validate_pack_set(packs: Iterable[PackId]) -> None:
    """Raise IncompatiblePackSelection if the set is not in ALLOWED_SETS.

    Exhaustively covers all 8 subsets of the 3 packs:
      {} {1} {2} {3} {1,2} {1,3} {2,3}✗ {1,2,3}✗
    """
    if frozenset(packs) not in ALLOWED_SETS:
        raise IncompatiblePackSelection(frozenset(packs))
