# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

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
    with pytest.raises(ValueError, match="'some' is not a valid Side"):
        Side.get("some")


def test_side_get_invalid_type() -> None:
    with pytest.raises(ValueError, match="'True' is not a valid Side"):
        Side.get(True)  # type: ignore


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
    with pytest.raises(ValueError, match="'some' is not a valid PositionOption"):
        PositionOption.get("some")


def test_position_option_get_invalid_type() -> None:
    with pytest.raises(ValueError, match="'True' is not a valid PositionOption"):
        PositionOption.get(True)  # type: ignore


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
                "start_index": -1,
            },
        ),
        (
            ElementInfo("D{}", PositionOption.DEFAULT, None, ""),
            {
                "annotation_format": "D{}",
                "position_option": PositionOption.DEFAULT,
                "position": None,
                "template_path": "",
                "start_index": -1,
            },
        ),
        (
            ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "", start_index=5),
            {
                "annotation_format": "SW{}",
                "position_option": PositionOption.DEFAULT,
                "position": {
                    "x": 0,
                    "y": 0,
                    "orientation": 0,
                    "side": Side.FRONT,
                },
                "template_path": "",
                "start_index": 5,
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


def test_element_info_from_dict_backward_compatibility() -> None:
    """Test that from_dict handles missing start_index (old files)"""
    data = {
        "annotation_format": "SW{}",
        "position_option": PositionOption.DEFAULT,
        "position": None,
        "template_path": "",
        # No start_index field - simulates old saved state
    }
    info = ElementInfo.from_dict(data)
    assert info.start_index == -1
    assert info.annotation_format == "SW{}"
    assert info.position_option == PositionOption.DEFAULT


def test_element_info_start_index_custom() -> None:
    """Test that custom start_index values are preserved"""
    info = ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "", start_index=10)
    assert info.start_index == 10

    # Test serialization round-trip
    data = asdict(info)
    assert data["start_index"] == 10

    restored = ElementInfo.from_dict(data)
    assert restored.start_index == 10
