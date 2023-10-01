from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, Flag
from typing import Optional


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
    RELATIVE = "Relative"
    PRESET = "Preset"
    CUSTOM = "Custom"
    UNCHANGED = "Unchaged"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def get(cls, name) -> PositionOption:
        if isinstance(name, str):
            value = name.replace("_", " ").title()
            return PositionOption(value)
        msg = f"'{name}' is not valid Position"
        raise ValueError(msg)


@dataclass
class ElementInfo:
    annotation_format: str
    position_option: PositionOption
    position: Optional[ElementPosition]
    template_path: str

    def to_dict(self) -> dict:
        value = {
            "annotation_format": self.annotation_format,
            "position_option": self.position_option,
            "position": {
                "relative_position": self.position.relative_position.to_list(),
                "orientation": self.position.orientation,
                "side": self.position.side.name,
            }
            if self.position
            else None,
            "template_path": self.template_path,
        }
        return value

    @classmethod
    def from_dict(cls, value: dict) -> ElementInfo:
        try:
            annotation_format = value["annotation_format"]
            position_option = PositionOption.get(value["position_option"])
            if position := value["position"]:
                x, y = position["relative_position"]
                orientation = position["orientation"]
                side = Side.get(position["side"])
                position = ElementPosition(Point(x, y), orientation, side)
            else:
                position = None
            template_path = value["template_path"]
            return ElementInfo(
                annotation_format, position_option, position, template_path
            )
        except Exception as e:
            msg = "Failed to create ElementInfo object"
            raise ValueError(msg) from e
