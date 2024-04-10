from __future__ import annotations

from dataclasses import asdict

import pytest

from kbplacer.defaults import ZERO_POSITION
from kbplacer.element_position import ElementInfo, PositionOption, Side


@pytest.mark.parametrize(
    "value,expected",
    [
        ("FRONT", Side.FRONT),
        ("fRoNt", Side.FRONT),
        ("BACK", Side.BACK),
        ("back", Side.BACK),
    ],
)
def test_side_get(value, expected) -> None:
    assert Side.get(value) == expected


def test_side_get_invalid() -> None:
    with pytest.raises(ValueError, match="'some' is not a valid Position"):
        Side.get("some")


def test_side_get_invalid_type() -> None:
    with pytest.raises(ValueError, match="'True' is not a valid Position"):
        Side.get(True)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Default", PositionOption.DEFAULT),
        ("DEFAULT", PositionOption.DEFAULT),
    ],
)
def test_position_option_get(value, expected) -> None:
    assert PositionOption.get(value) == expected


def test_position_option_get_invalid() -> None:
    with pytest.raises(ValueError, match="'Some' is not a valid PositionOption"):
        PositionOption.get("some")


def test_position_option_get_invalid_type() -> None:
    with pytest.raises(ValueError, match="'True' is not a valid PositionOption"):
        PositionOption.get(True)


@pytest.mark.parametrize(
    "info,expected",
    [
        (
            ElementInfo("D{}", PositionOption.DEFAULT, ZERO_POSITION, ""),
            {
                "annotation_format": "D{}",
                "position_option": PositionOption.DEFAULT,
                "position": {
                    "x": 0,
                    "y": 0,
                    "orientation": 0,
                    "side": Side.FRONT,
                },
                "template_path": "",
            },
        ),
        (
            ElementInfo("D{}", PositionOption.DEFAULT, None, ""),
            {
                "annotation_format": "D{}",
                "position_option": PositionOption.DEFAULT,
                "position": None,
                "template_path": "",
            },
        ),
    ],
)
def test_element_info_dict_conversions(info, expected) -> None:
    result = asdict(info)
    assert result == expected
    assert ElementInfo.from_dict(result) == info


def test_element_info_from_empty_dict() -> None:
    with pytest.raises(TypeError):
        ElementInfo.from_dict({})
