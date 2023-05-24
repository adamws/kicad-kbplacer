from __future__ import annotations

from dataclasses import dataclass
from enum import Flag


class Side(Flag):
    FRONT = False
    BACK = True


@dataclass
class Point:
    x: float
    y: float

    def to_list(self) -> list[float]:
        return [self.x, self.y]


@dataclass
class ElementPosition:
    relative_position: Point
    orientation: float
    side: Side
