"""Geometry helpers in the unit square (all coordinates normalised 0..1)."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

Compass = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

Point = tuple[float, float]


def centroid(x: float, y: float, w: float, h: float) -> Point:
    return (x + w / 2.0, y + h / 2.0)


def bottom_center(x: float, y: float, w: float, h: float) -> Point:
    """Ground-contact point; better than the centroid for road geometry."""
    return (x + w / 2.0, y + h)


def point_in_polygon(point: Point, polygon: Sequence[Sequence[float]]) -> bool:
    if len(polygon) < 3:
        return False
    px, py = point
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        intersects = (yi > py) != (yj > py) and (
            px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def side_of_line(point: Point, a: Sequence[float], b: Sequence[float]) -> float:
    """Signed area sign: >0 left of a→b, <0 right, 0 on the line."""
    return (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])


def crossed_gate(prev: Point, curr: Point, gate: Sequence[Sequence[float]]) -> bool:
    """True when the path prev→curr enters the gate.

    A gate with two points is a line: crossing means changing sides while the
    crossing point lies within the segment's extent. Three or more points form
    a polygon: crossing means entering it.
    """
    if len(gate) >= 3:
        return (not point_in_polygon(prev, gate)) and point_in_polygon(curr, gate)
    if len(gate) < 2:
        return False
    a, b = gate[0], gate[1]
    s1 = side_of_line(prev, a, b)
    s2 = side_of_line(curr, a, b)
    if s1 == 0 or s2 == 0 or (s1 > 0) == (s2 > 0):
        return False
    # Project crossing point onto the segment and require it to be inside.
    t = s1 / (s1 - s2)
    cx = prev[0] + (curr[0] - prev[0]) * t
    cy = prev[1] + (curr[1] - prev[1]) * t
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    seg_len_sq = (bx - ax) ** 2 + (by - ay) ** 2 or 1e-12
    u = ((cx - ax) * (bx - ax) + (cy - ay) * (by - ay)) / seg_len_sq
    return -0.05 <= u <= 1.05


def compass_from_vector(dx: float, dy: float) -> Compass | None:
    """Image coordinates: +y is down, so north is negative dy."""
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return None
    import math

    angle = math.degrees(math.atan2(-dy, dx))  # 0 = east, 90 = north
    labels: list[Compass] = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]
    idx = int(((angle + 22.5) % 360) // 45)
    return labels[idx]
