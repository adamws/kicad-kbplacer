from __future__ import annotations

import pytest

from kbplacer.defaults import ZERO_POSITION
from kbplacer.element_position import ElementInfo, Point, PositionOption, Side


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


def test_point_to_list() -> None:
    assert Point(1, 2).to_list() == [1, 2]


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
                    "relative_position": [0, 0],
                    "orientation": 0,
                    "side": "FRONT",
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
    result = info.to_dict()
    assert result == expected
    assert ElementInfo.from_dict(result) == info


def test_element_info_from_empty_dict() -> None:
    with pytest.raises(ValueError, match="Failed to create ElementInfo object"):
        ElementInfo.from_dict({})
