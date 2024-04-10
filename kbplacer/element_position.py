from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Side(str, Enum):
    FRONT = "Front"
    BACK = "Back"

    @classmethod
    def get(cls, name) -> Side:
        if isinstance(name, str):
            if name.upper() == "FRONT":
                return Side.FRONT
            elif name.upper() == "BACK":
                return Side.BACK
        msg = f"'{name}' is not a valid Position"
        raise ValueError(msg)


@dataclass
class ElementPosition:
    x: float
    y: float
    orientation: float
    side: Side


class PositionOption(str, Enum):
    DEFAULT = "Default"
    RELATIVE = "Relative"
    PRESET = "Preset"
    CUSTOM = "Custom"
    UNCHANGED = "Unchanged"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def get(cls, name) -> PositionOption:
        if isinstance(name, str):
            value = name.replace("_", " ").title()
            return PositionOption(value)
        msg = f"'{name}' is not a valid PositionOption"
        raise ValueError(msg)


@dataclass
class ElementInfo:
    annotation_format: str
    position_option: PositionOption
    position: Optional[ElementPosition]
    template_path: str

    @classmethod
    def from_dict(cls, data: dict) -> ElementInfo:
        position_data = data.pop("position", None)
        position = ElementPosition(**position_data) if position_data else None
        return cls(position=position, **data)
