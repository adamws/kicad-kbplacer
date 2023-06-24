from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, Flag


class Side(Flag):
    FRONT = False
    BACK = True

    @classmethod
    def get(cls, name) -> Side:
        if isinstance(name, str):
            if name.upper() == "FRONT":
                return Side.FRONT
            elif name.upper() == "BACK":
                return Side.BACK
        msg = f"'{name}' is not valid Position"
        raise ValueError(msg)


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


class PositionOption(str, Enum):
    DEFAULT = "Default"
    CURRENT_RELATIVE = "Current Relative"
    CUSTOM = "Custom"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def get(cls, name) -> PositionOption:
        if isinstance(name, str):
            value = name.replace("_", " ").title()
            return PositionOption(value)
        msg = f"'{name}' is not valid Position"
        raise ValueError(msg)
