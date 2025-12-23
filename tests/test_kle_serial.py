# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import locale
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import unittest
from copy import copy
from pathlib import Path
from typing import Tuple

import pytest
import yaml
from lzstring import LZString

from kbplacer.kle_serial import (
    KEY_MAX_LABELS,
    Key,
    Keyboard,
    KeyboardTag,
    MatrixAnnotatedKeyboard,
    get_explicit_spacing_from_file,
    get_keyboard,
    get_keyboard_from_file,
    layout_classification,
    parse_ergogen_points,
    parse_kle,
    parse_qmk,
    parse_via,
)

from .conftest import add_url_to_report

logger = logging.getLogger(__name__)
lz = LZString()


def __minify(string: str) -> str:
    for ch in ["\n", " "]:
        string = string.replace(ch, "")
    return string


def keyboard_to_url(tmpdir, keyboard: Keyboard) -> None:
    kle_raw = "[" + keyboard.to_kle() + "]"
    encoded = lz.compressToEncodedURIComponent(kle_raw)
    kle_url = "https://editor.keyboard-tools.xyz/#share=" + encoded
    add_url_to_report(tmpdir, kle_url)


# single key layouts with various labels:
@pytest.mark.parametrize(
    # fmt: off
    "layout,expected",
    [
        ([["x"]],                         [          "x"]), # top-left
        ([[{"a":5},"x"]],                 [None,     "x"]), # top-center
        ([["\n\nx"]],                (2 * [None]) + ["x"]), # top-right
        ([[{"a":6},"x"]],            (3 * [None]) + ["x"]), # center-left
        ([[{"a":7},"x"]],            (4 * [None]) + ["x"]), # center
        ([[{"a":6},"\n\nx"]],        (5 * [None]) + ["x"]), # center-right
        ([["\nx"]],                  (6 * [None]) + ["x"]), # bottom-left
        ([[{"a":5},"\nx"]],          (7 * [None]) + ["x"]), # bottom-center
        ([["\n\n\nx"]],              (8 * [None]) + ["x"]), # bottom-right
        ([[{"a":3},"\n\n\n\nx"]],    (9 * [None]) + ["x"]), # front-left
        ([[{"a":7},"\n\n\n\nx"]],   (10 * [None]) + ["x"]), # front-center
        ([[{"a":3},"\n\n\n\n\nx"]], (11 * [None]) + ["x"]), # front-right
        ([[{"a":0},"x\nx\nx\nx\nx\nx\nx\nx\nx\nx\nx\nx"]], (12 * ["x"])) # all at once
    ],
    # fmt: on
)
def test_labels(layout, expected) -> None:
    result = parse_kle(layout)
    assert result.keys[0].labels == expected
    # check if reverse operation works as well:
    assert [json.loads(result.to_kle())] == layout


@pytest.mark.parametrize(
    # fmt: off
    "layout,expected",
    [
        ([["1,2"]], ("1", "2")),
        ([["1, 2"]], ("1", "2")),
        ([[" 1, 2"]], ("1", "2")),
        ([["R1, R2"]], ("R1", "R2")),
        ([["R1,R2 "]], ("R1", "R2")),
    ],
    # fmt: on
)
def test_via_labels(layout, expected) -> None:
    keyboard = parse_kle(layout)
    annotated_keyboard = MatrixAnnotatedKeyboard.from_keyboard(keyboard)
    assert (
        MatrixAnnotatedKeyboard.get_matrix_position(annotated_keyboard.keys[0])
        == expected
    )


@pytest.mark.parametrize(
    # fmt: off
    "layout",
    [
        ([["1-2"]]),
        ([["1,2,3"]]),
    ],
    # fmt: on
)
def test_illegal_via_labels(layout) -> None:
    with pytest.raises(
        RuntimeError,
        match="Keyboard object not convertible to matrix annotated keyboard: "
        "Matrix coordinates label missing or invalid",
    ):
        keyboard = parse_kle(layout)
        annotated_keyboard = MatrixAnnotatedKeyboard.from_keyboard(keyboard)
        MatrixAnnotatedKeyboard.get_matrix_position(annotated_keyboard.keys[0])


class LabelsTestCase(unittest.TestCase):
    def test_too_many_labels(self) -> None:
        labels = "\n".join(13 * ["x"])
        layout = [[{"a": 0}, labels]]
        expected = 12 * ["x"]
        with self.assertLogs("kbplacer.kle_serial", level="INFO") as cm:
            result = parse_kle(layout)
        assert result.keys[0].labels == expected
        self.assertEqual(
            cm.output,
            [
                f"WARNING:kbplacer.kle_serial:Illegal key labels: '{repr(labels)}'. "
                "Labels string can contain 12 '\\n' separated items, "
                "ignoring redundant values."
            ],
        )


@pytest.mark.parametrize(
    # fmt: off
    "layout,expected_labels,expected_text_size",
    [
        ([[{"fa":[6]},"x"]],         [          "x"], [               6]),
        ([[{"a":5,"fa":[6]},"x"]],   [     None,"x"], [          None,6]),
        ([[{"fa":[0,0,6]},"\n\nx"]], [None,None,"x"], [     None,None,6]),
        ([[{"f2":6},"\nx"]],    (6 * [None]) + ["x"], (6 * [None]) + [6]),
    ],
    # fmt: on
)
def test_labels_text_size(layout, expected_labels, expected_text_size) -> None:
    result = parse_kle(layout)
    assert result.keys[0].labels == expected_labels
    assert result.keys[0].textSize == expected_text_size
    # check if reverse operation works as well:
    assert [json.loads(result.to_kle())] == layout


def test_labels_colors() -> None:
    # fmt: off
    layout = [[
        {"t": "#ff0000\n\n\n\n\n\n\n\n\n\n#0018ff"},"x\n\n\n\n\n\n\n\n\n\nx",
        {"t": "#ff0000\n\n\n\n\n\n\n\n\n#736827"},"x\n\n\n\n\n\n\n\n\nx",
        {"t": "#210e0e\n\n\n\n\n\n\n\n\n#736827"},"x\n\n\n\n\n\n\n\n\nx\nx",
        {"t": "#000000\n\n\n\n\n\n\n\n\n#a80000"},"x\n\n\n\n\n\n\n\n\nx\nx",
    ]]
    # fmt: on
    result = parse_kle(layout)
    assert [json.loads(result.to_kle())] == layout


def test_float_accuracy() -> None:
    # few first keys from atreus preset
    atreus = (
        '[[{"r":10,"rx":1,"y":-0.1,"x":2},"E"],'
        '[{"y":-0.65,"x":1},"W",{"x":1},"R"],'
        '[{"y":-0.75},"Q"],'
        '[{"y":-0.9,"x":4},"T"],'
        '[{"y":-0.7,"x":2},"D"],'
        '[{"y":-0.65,"x":1},"S",{"x":1},"F"]]'
    )
    layout = json.loads(atreus)
    result = parse_kle(layout)
    positions = [(key.x, key.y) for key in result.keys]
    expected_positions = [
        (3, -0.1),  # E
        (2, 0.25),  # W
        (4, 0.25),  # R
        (1, 0.50),  # Q
        (5, 0.60),  # T
        (3, 0.90),  # D - without rounding in parser this would be
        #                 incorrectly set to (3, 0.9000000000000001)
        #                 accuracy of 6 digit is more than enough and looks cleaner in
        #                 json files
        (2, 1.25),  # S
        (4, 1.25),  # F
    ]
    assert positions == expected_positions


def test_if_produces_valid_json() -> None:
    result = parse_kle([["x"]])
    assert (
        result.to_json() == '{"meta": '
        '{"author": "", "backcolor": "#eeeeee", "background": null, "name": "", '
        '"notes": "", "radii": "", "switchBrand": "", "switchMount": "", "switchType": "", '
        '"spacing_x": 19.05, "spacing_y": 19.05}, '
        '"keys": [{"color": "#cccccc", "labels": ["x"], "textColor": [], "textSize": [], '
        '"default": {"textColor": "#000000", "textSize": 3}, "x": 0, "y": 0, "width": 1, '
        '"height": 1, "x2": 0, "y2": 0, "width2": 1, "height2": 1, "rotation_x": 0, '
        '"rotation_y": 0, "rotation_angle": 0, "decal": false, "ghost": false, "stepped": false, '
        '"nub": false, "profile": "", "sm": "", "sb": "", "st": ""}]}'
    )


def __get_invalid_parse_parameters():
    test_params = []
    test_params.append(pytest.param([], id="empty-list"))
    test_params.append(pytest.param({}, id="empty-dict"))
    test_params.append(pytest.param("", id="empty-string"))
    test_params.append(pytest.param('[["x"]]', id="some-string"))
    test_params.append(pytest.param(["", ""], id="list-of-unexpected-type"))
    test_params.append(pytest.param([{}, {}], id="list-with-wrong-dict-position"))
    test_params.append(pytest.param([[], {}], id="list-with-wrong-dict-position-2"))
    test_params.append(pytest.param([[True]], id="unexpected-type"))
    return test_params


@pytest.mark.parametrize("input_object", __get_invalid_parse_parameters())
def test_parse_kle_invalid_schema(input_object) -> None:
    with pytest.raises(RuntimeError):
        parse_kle(input_object)


def test_parse_kle_invalid_key_rotation() -> None:
    with pytest.raises(RuntimeError):
        # Rotation can only be specified on the first key in the row
        layout = [["0", {"r": 15, "rx": 1, "ry": 2}, "1"]]
        parse_kle(layout)


def test_keyboard_from_invalid_type() -> None:
    with pytest.raises(TypeError):
        Keyboard.from_json("{}")  # type: ignore


def test_keyboard_from_invalid_schema() -> None:
    with pytest.raises(KeyError):
        Keyboard.from_json({})  # type: ignore


def get_reference(path: Path):
    with open(path, "r") as f:
        layout: str = f.read()
        reference_dict = json.loads(layout)
        return Keyboard.from_json(reference_dict)


def __get_parameters():
    test_params = []
    # some standard layouts and complex samples from keyboard-layout-editor.com
    kle_presets = [
        "ansi-104-big-ass-enter",
        "ansi-104",
        "apple-wireless",
        "atreus",
        "ergodox",
        "iso-105",
        "kinesis-advantage",
        "symbolics-spacecadet",
        "three-keys-middle-non-default-smsbst-right-ghosted",
    ]
    for f in kle_presets:
        param = pytest.param(
            f"./data/kle-layouts/{f}.json",
            f"./data/kle-layouts/{f}-internal.json",
            id=f,
        )
        test_params.append(param)

    examples = ["2x2", "3x2-sizes", "2x3-rotations", "1x4-rotations-90-step"]
    for e in examples:
        param = pytest.param(
            f"../examples/{e}/kle-annotated.json",
            f"../examples/{e}/kle-internal.json",
            id=e,
        )
        test_params.append(param)

    return test_params


@pytest.mark.parametrize("layout_file,reference_file", __get_parameters())
@pytest.mark.parametrize("get_function", [parse_kle, get_keyboard])
def test_with_kle_references(
    layout_file, reference_file, get_function, request
) -> None:
    test_dir = request.fspath.dirname

    reference = get_reference(Path(test_dir) / reference_file)

    with open(Path(test_dir) / layout_file, "r") as f:
        layout = json.load(f)
        result = get_function(layout)
        assert result == reference

        f.seek(0)
        kle_result = json.loads("[" + __minify(result.to_kle()) + "]")
        expected = json.loads(__minify(f.read()))
        assert kle_result == expected


@pytest.mark.parametrize("example", ["2x2", "1x2-with-2U-bottom", "1x1-rotated"])
@pytest.mark.parametrize("get_function", [parse_ergogen_points, get_keyboard])
def test_with_ergogen(tmpdir, example, get_function, request) -> None:
    test_dir = request.fspath.dirname

    reference = get_reference(
        Path(test_dir) / f"data/ergogen-layouts/{example}-internal.json"
    )

    # very simple example layout
    with open(Path(test_dir) / f"data/ergogen-layouts/{example}.json", "r") as f:
        layout = json.load(f)
        result = get_function(layout)
        keyboard_to_url(tmpdir, result)
        assert result == reference


def _layout_collapse(layout) -> MatrixAnnotatedKeyboard:
    tmp = parse_kle(layout)
    keyboard = MatrixAnnotatedKeyboard.from_keyboard(tmp)
    keyboard.collapse()
    return keyboard


def test_iso_enter_layout_collapse() -> None:
    # fmt: off
    layout =  [
        [{"x":1.25},"1,12",{"w":1.5},"1,13\n\n\n1,0",{"x":1.25,"w":1.25,"h":2,"w2":1.5,"h2":1,"x2":-0.25},"1,13\n\n\n1,1"],
        [{"x":0.5},"2,11",{"w":2.25},"2,12\n\n\n1,0",{"x":0.25},"2,12\n\n\n1,1"],
        ["3,11",{"w":2.75},"3,12\n\n\n3,0",{"x":0.25,"w":1.75},"3,12\n\n\n3,1","3,13\n\n\n3,1"]
    ]
    expected = [
        [{"x":1.25},"1,12",{"w":1.5},"1,13\n\n\n1,0",{"x":-1.25,"w":1.25,"h":2,"w2":1.5,"h2":1,"x2":-0.25},"1,13\n\n\n1,1"],
        [{"x":0.5},"2,11",{"w":2.25},"2,12\n\n\n1,0",{"x":-2.25},"2,12\n\n\n1,1"],
        ["3,11",{"w":2.75},"3,12\n\n\n3,0",{"x":-2.75,"w":1.75},"3,12\n\n\n3,1","3,13\n\n\n3,1"]
    ]
    # fmt: on
    result = _layout_collapse(layout)
    expected_keyboard = parse_kle(expected)
    expected_keyboard = MatrixAnnotatedKeyboard.from_keyboard(expected_keyboard)
    expected_keyboard.collapsed = True
    assert result == expected_keyboard


def test_bottom_row_collapse_no_extra_keys() -> None:
    # this alternative layout does not introduce any new keys
    # because all are duplicate of original bottom row with the except
    # of two which are missing (and proper alignment forced by decals)
    # fmt: off
    layout = [
        [{"w":1.5},"4,0\n\n\n0,0","4,1\n\n\n0,0",{"w":1.5},"4,2\n\n\n0,0",{"w":7},"4,6\n\n\n0,0",{"w":1.5},"4,10\n\n\n0,0","4,11\n\n\n0,0",{"w":1.5},"4,12\n\n\n0,0"],
        [{"y":0.75,"w":1.5,"d":True},"\n\n\n0,1","4,1\n\n\n0,1",{"w":1.5},"4,2\n\n\n0,1",{"w":7},"4,6\n\n\n0,1",{"w":1.5},"4,10\n\n\n0,1","4,11\n\n\n0,1",{"w":1.5,"d":True},"\n\n\n0,1"]
    ]
    expected = [
        [{"w":1.5},"4,0\n\n\n0,0","4,1\n\n\n0,0",{"w":1.5},"4,2\n\n\n0,0",{"w":7},"4,6\n\n\n0,0",{"w":1.5},"4,10\n\n\n0,0","4,11\n\n\n0,0",{"w":1.5},"4,12\n\n\n0,0"],
    ]
    # fmt: on
    result = _layout_collapse(layout)
    expected_keyboard = parse_kle(expected)
    expected_keyboard = MatrixAnnotatedKeyboard.from_keyboard(expected_keyboard)
    expected_keyboard.collapsed = True
    assert result == expected_keyboard
    assert len(result.alternative_keys) == 0


def test_bottom_row_decal_handling() -> None:
    # fmt: off
    layout = [
        [{"w":1.5},"4,0\n\n\n0,0","4,1\n\n\n0,0",{"w":1.5},"4,2\n\n\n0,0"],
        [{"y":0.75,"w":1.5,"d":True},"\n\n\n0,1",{"w":2.5},"4,1\n\n\n0,1"]
    ]
    expected = [
        [{"w":1.5},"4,0\n\n\n0,0","4,1\n\n\n0,0",{"x":-1,"w":2.5},"4,1\n\n\n0,1",{"x":-1.5,"w":1.5},"4,2\n\n\n0,0"]
    ]
    # fmt: on
    result = _layout_collapse(layout)
    expected_keyboard = parse_kle(expected)
    expected_keyboard = MatrixAnnotatedKeyboard.from_keyboard(expected_keyboard)
    expected_keyboard.collapsed = True
    assert result == expected_keyboard
    assert len(result.alternative_keys) == 1


def test_collapse_ignores_decal_keys_in_default_key_group() -> None:
    # same as `test_bottom_row_decal_handling` but with decal key
    # with missing labels in default row. Its labels should be ignored and it should
    # be propagated to collapsed layout without change
    # fmt: off
    layout = [
        [{"w":1.5},"4,0\n\n\n0,0","4,1\n\n\n0,0",{"w":1.5},"4,2\n\n\n0,0",{"d":True},""],
        [{"y":0.75,"w":1.5,"d":True},"\n\n\n0,1",{"w":2.5},"4,1\n\n\n0,1"]
    ]
    expected = [
        [{"w":1.5},"4,0\n\n\n0,0","4,1\n\n\n0,0",{"x":-1,"w":2.5},"4,1\n\n\n0,1",{"x":-1.5,"w":1.5},"4,2\n\n\n0,0",{"d":True},""]
    ]
    # fmt: on
    result = _layout_collapse(layout)
    expected_keyboard = parse_kle(expected)
    expected_keyboard = MatrixAnnotatedKeyboard.from_keyboard(expected_keyboard)
    expected_keyboard.collapsed = True
    assert result == expected_keyboard
    assert len(result.alternative_keys) == 1


def test_collapse_detects_duplicated_keys() -> None:
    # middle alternative key should be removed because it belongs to the same net,
    # and although it is different size than default choice, the center of a switch
    # is in the same place (so using both would result in overlapping/duplicated
    # footprint)
    # fmt: off
    layout = [
        [{"w":7},"4,6\n\n\n2,0"],
        [{"y":0.5,"w":3},"4,4\n\n\n2,1","4,6\n\n\n2,1",{"w":3},"4,8\n\n\n2,1"]
    ]
    expected = [
        [{"w":7},"4,6\n\n\n2,0",{"x":-7,"w":3},"4,4\n\n\n2,1",{"x":1,"w":3},"4,8\n\n\n2,1"]
    ]
    # fmt: on
    result = _layout_collapse(layout)
    expected_keyboard = parse_kle(expected)
    expected_keyboard = MatrixAnnotatedKeyboard.from_keyboard(expected_keyboard)
    expected_keyboard.collapsed = True
    assert result == expected_keyboard
    assert len(result.alternative_keys) == 2


def test_duplicate_matrix_position_in_default_group_not_allowed() -> None:
    # fmt: off
    layout = [
        [{"w":1.5},"4,0\n\n\n0,0","4,1\n\n\n0,0",{"w":1.5},"4,1\n\n\n0,0"],
        [{"w":2.5},"4,1\n\n\n0,1"]
    ]
    # fmt: on
    with pytest.raises(
        RuntimeError,
        match="Keyboard object not convertible to matrix annotated keyboard: "
        "Duplicate matrix position for default layout keys not allowed",
    ):
        _ = _layout_collapse(layout)


def test_illegal_layout_option_label() -> None:
    # fmt: off
    layout = [
        [{"w":1.5},"4,0\n\n\n0,0","4,1\n\n\n0,0"],
        [{"w":2.5},"4,1\n\n\n0,1,2"]
    ]
    # fmt: on
    with pytest.raises(
        ValueError, match=r"Unexpected number of ',' delimited elements in key label"
    ):
        _ = _layout_collapse(layout)


@pytest.mark.parametrize("example", ["0_sixty", "crkbd", "wt60_a", "wt60_d"])
@pytest.mark.parametrize("get_function", [parse_via, get_keyboard])
@pytest.mark.parametrize("collapses", [1, 2])
def test_with_via_layouts(tmpdir, request, example, get_function, collapses) -> None:
    test_dir = request.fspath.dirname

    def _reference_keyboard(filename: str) -> MatrixAnnotatedKeyboard:
        reference = get_reference(Path(test_dir) / "data/via-layouts" / filename)
        return MatrixAnnotatedKeyboard.from_keyboard(reference)

    with open(Path(test_dir) / f"data/via-layouts/{example}.json", "r") as f:
        layout = json.load(f)
        result = get_function(layout)
        assert isinstance(result, MatrixAnnotatedKeyboard)
        # calling MatrixAnnotatedKeyboard.from_keyboard on
        # MatrixAnnotatedKeyboard must be noop:
        assert MatrixAnnotatedKeyboard.from_keyboard(result) == result
        keyboard_to_url(tmpdir, result)
        assert result == _reference_keyboard(f"{example}-internal.json")
        # calling this multiple times should not matter
        for _ in range(0, collapses):
            result.collapse()
        result.sort_keys()
        reference_collapsed = _reference_keyboard(f"{example}-internal-collapsed.json")
        assert result.keys == reference_collapsed.keys
        assert result.alternative_keys == reference_collapsed.alternative_keys
        # check iterator
        keys_without_alternative = list(result.key_iterator(ignore_alternative=True))
        assert all(
            elem not in keys_without_alternative for elem in result.alternative_keys
        )
        keys_with_alternative = list(result.key_iterator(ignore_alternative=False))
        assert result.keys == keys_without_alternative
        assert result.keys + result.alternative_keys == keys_with_alternative

        # convert back to `Keyboard` dataclass preserving expected key order:
        result = result.to_keyboard()
        reference_collapsed = reference_collapsed.to_keyboard()
        assert result.keys == reference_collapsed.keys


@pytest.mark.parametrize("example", ["0_sixty", "crkbd", "wt60_a", "wt60_d"])
@pytest.mark.parametrize("get_function", [parse_qmk, get_keyboard])
def test_with_qmk_layouts(tmpdir, request, example, get_function) -> None:
    test_dir = request.fspath.dirname

    with open(Path(test_dir) / f"data/qmk-layouts/{example}.json", "r") as f:
        layout = json.load(f)
        result = get_function(layout)
        assert isinstance(result, MatrixAnnotatedKeyboard)
        result = result.to_keyboard()
        keyboard_to_url(tmpdir, result)
        # qmk layouts are already 'collapsed', i.e. keys are at final positions
        # and there are no duplicates
        reference = get_reference(
            Path(test_dir) / "data/qmk-layouts" / f"{example}-internal-collapsed.json"
        )
        assert result.keys == reference.keys

        # qmk layout should be convertible to `MatrixAnnotatedKeyboard` type
        result = MatrixAnnotatedKeyboard.from_keyboard(result)
        # there is no automatic detection if layout is already collapsed (prior to calling `collapse`
        # for the first time, this would require implementing rotated polygons collision detection
        # which is too much work for now for this one edge case
        result.collapsed = True
        result.collapse()

        reference_collapsed = MatrixAnnotatedKeyboard.from_keyboard(reference)
        assert result.keys == reference_collapsed.keys
        assert result.alternative_keys == reference_collapsed.alternative_keys


class TestQmkCorruptedData:
    @pytest.fixture()
    def qmk(self, request):
        test_dir = request.fspath.dirname
        example = "0_sixty"

        with open(Path(test_dir) / f"data/qmk-layouts/{example}.json", "r") as f:
            layout = json.load(f)
            yield layout

    def test_missing_layouts_value(self, qmk) -> None:
        del qmk["layouts"]
        with pytest.raises(
            RuntimeError, match="Invalid QMK data, required 'layouts' value not found"
        ):
            _ = parse_qmk(qmk)

    def test_missing_layout_value(self, qmk) -> None:
        key_to_delete_from = random.choice(list(qmk["layouts"].keys()))
        del qmk["layouts"][key_to_delete_from]["layout"]
        with pytest.raises(
            RuntimeError, match="Invalid QMK data, required 'layout' value not found"
        ):
            _ = parse_qmk(qmk)

    def test_invalid_layouts_type(self, qmk) -> None:
        layout_to_corrupt = random.choice(list(qmk["layouts"].keys()))
        qmk["layouts"][layout_to_corrupt]["layout"][
            0
        ] = "expected dict, this is a string"
        with pytest.raises(
            RuntimeError,
            match="Unexpected data appeared while parsing QMK layout: '.*'",
        ):
            _ = parse_qmk(qmk)

    @pytest.mark.parametrize("new_value", ["string", [0, 1, 3], [], [0], {}])
    def test_invalid_matrix(self, qmk, new_value) -> None:
        layout_to_corrupt = random.choice(list(qmk["layouts"].keys()))
        qmk["layouts"][layout_to_corrupt]["layout"][0]["matrix"] = new_value
        with pytest.raises(
            RuntimeError,
            match=re.escape(
                f"Unexpected key matrix position appeared while parsing QMK layout: '{new_value}'"
            ),
        ):
            _ = parse_qmk(qmk)


@pytest.mark.parametrize(
    "layout,expected_order",
    [
        # fmt: off
        (
            # nothing to sort
            [["4,0","4,1","4,2"]],
            [0, 1, 2],
        ),
        (
            # labels can have prefix and should get sorted
            [["R4,C0","R4,C2","R4,C1"]],
            [0, 2, 1],
        ),
        (
            # alternative layouts should be preserved
            [
                [{"w":1.5},"4,0\n\n\n0,0","4,1\n\n\n0,0",{"w":1.5},"4,2\n\n\n0,0",{"d":True},""],
                [{"y":0.75,"w":1.5,"d":True},"\n\n\n0,1",{"w":2.5},"4,1\n\n\n0,1"]
                                                                   # ^ this is 5th key, should end up
                                                                   # before '4,2' (3rd key) because
                                                                   # earlier in matrix
            ],
            [0, 1, 5, 2],
        ),
        (
            [
                [{"w":7},"4,6\n\n\n2,0"],
                [{"y":0.5,"w":3},"4,4\n\n\n2,1","4,6\n\n\n2,1",{"w":3},"4,8\n\n\n2,1"]
                                 # ^ this is 2nd key which should be first after sort
            ],
            [1, 0, 2, 3],
        )
        # fmt: on
    ],
)
def test_keys_in_matrix_order(layout, expected_order) -> None:
    tmp = parse_kle(layout)
    layout_order = copy(tmp.keys)

    keyboard = MatrixAnnotatedKeyboard.from_keyboard(tmp)
    keys = keyboard.keys_in_matrix_order()

    for k, index in zip(keys, expected_order):
        assert k == layout_order[index]


@pytest.mark.parametrize(
    "layout,reason",
    [
        # fmt: off
        ([["R4,C"]], "Unexpected format of matrix coordinates label part"),
        ([["0,0","R0,1"]], "Matrix position prefix must be common across rows and columns"),
        # fmt: on
    ],
)
def test_keys_in_matrix_order_illegal_labels(layout, reason) -> None:
    tmp = parse_kle(layout)
    error = "Keyboard object not convertible to matrix annotated keyboard: "
    with pytest.raises(RuntimeError, match=error + reason):
        _ = MatrixAnnotatedKeyboard.from_keyboard(tmp)


class TestKleSerialCli:
    def _run_subprocess(
        self,
        package_path,
        package_name,
        args: dict[str, str] = {},
    ) -> subprocess.Popen:
        kbplacer_args = [
            "python3",
            "-m",
            f"{package_name}.kle_serial",
        ]
        for k, v in args.items():
            kbplacer_args.append(k)
            if v:
                kbplacer_args.append(v)

        env = os.environ.copy()
        p = subprocess.Popen(
            kbplacer_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            cwd=package_path,
            env=env,
        )
        return p

    @pytest.fixture()
    def example_isolation(self, request, tmpdir, example) -> Tuple[str, str]:
        test_dir = request.fspath.dirname
        source_dir = f"{test_dir}/../examples/{example}"
        shutil.copy(f"{source_dir}/kle-annotated.json", tmpdir)
        shutil.copy(f"{source_dir}/kle-internal.json", tmpdir)
        return f"{tmpdir}/kle-annotated.json", f"{tmpdir}/kle-internal.json"

    @pytest.mark.parametrize(
        "example", ["2x2", "3x2-sizes", "2x3-rotations", "1x4-rotations-90-step"]
    )
    def test_kle_file_convert(
        self, package_path, package_name, example_isolation
    ) -> None:
        raw = example_isolation[0]
        raw_tmp = Path(raw).with_suffix(".json.tmp")
        with open(raw, "r") as f:
            raw_json = json.load(f)

        internal = example_isolation[1]
        internal_tmp = Path(internal).with_suffix(".json.tmp")
        with open(internal, "r") as f:
            internal_json = json.load(f)

        p = self._run_subprocess(
            package_path,
            package_name,
            {
                "--in": raw,
                "--inform": "KLE_RAW",
                "--out": str(internal_tmp),
                "--outform": "KLE_INTERNAL",
                "--text": "",
            },
        )
        p.communicate()
        assert p.returncode == 0

        with open(internal_tmp, "r") as f:
            assert json.load(f) == internal_json

        p = self._run_subprocess(
            package_path,
            package_name,
            {
                "--in": str(internal_tmp),
                "--inform": "KLE_INTERNAL",
                "--out": str(raw_tmp),
                "--outform": "KLE_RAW",
                "--text": "",
            },
        )
        p.communicate()
        assert p.returncode == 0

        with open(raw_tmp, "r") as f:
            assert json.load(f) == raw_json

    @pytest.mark.parametrize(
        "example",
        ["0_sixty", "crkbd", "wt60_a", "wt60_d"],
    )
    @pytest.mark.parametrize(
        "inform,collapse",
        [
            ("KLE_VIA", False),
            ("KLE_VIA", True),
            ("QMK", False),  # QMK layout can't be collapsed
        ],
    )
    @pytest.mark.parametrize("outform", ["KLE_INTERNAL", "KLE_RAW"])
    def test_via_and_qmk_file_convert(
        self,
        request,
        tmpdir,
        package_path,
        package_name,
        example,
        inform,
        collapse,
        outform,
    ) -> None:
        test_dir = request.fspath.dirname
        data_dir = f"{test_dir}/data"

        layout_dir = "via-layouts" if inform == "KLE_VIA" else "qmk-layouts"
        layout_file = f"{data_dir}/{layout_dir}/{example}.json"

        layout_in = f"{tmpdir}/{example}.json"
        shutil.copy(layout_file, layout_in)
        tmp_file = Path(layout_in).with_suffix(".json.tmp")

        args = {
            "--in": layout_in,
            "--inform": inform,
            "--out": str(tmp_file),
            "--outform": outform,
            "--text": "",
        }
        if collapse:
            args["--collapse"] = ""

        p = self._run_subprocess(package_path, package_name, args)
        p.communicate()
        assert p.returncode == 0

        if (inform == "KLE_VIA" and collapse) or inform == "QMK":
            reference_name = f"{example}-internal-collapsed.json"
        else:
            reference_name = f"{example}-internal.json"

        with open(Path(data_dir) / f"{layout_dir}/{reference_name}", "r") as f:
            reference = json.load(f)

        if outform == "KLE_RAW":
            keyboard = Keyboard.from_json(reference)
            result = keyboard.to_kle()
            result = "[" + result + "]"
            reference = json.loads(result)

        with open(tmp_file, "r") as f:
            assert json.load(f) == reference

    @pytest.mark.parametrize(
        "example,ergogen_filter",
        [
            ("a-dux", ""),
            ("absolem-simple", ""),
            ("corney-island", "^(matrix|thumbfan)"),
        ],
    )
    def test_ergogen_file_convert(
        self, request, tmpdir, package_path, package_name, example, ergogen_filter
    ) -> None:
        test_dir = request.fspath.dirname
        data_dir = f"{test_dir}/data"

        layout_file = f"{tmpdir}/layout.json"
        with open(f"{data_dir}/ergogen-layouts/{example}-points.yaml", "r") as f:
            y = yaml.safe_load(f)
            with open(layout_file, "w") as f2:
                json.dump(y, f2)
        tmp_file = Path(layout_file).with_suffix(".json.tmp")

        args = {
            "--in": layout_file,
            "--inform": "ERGOGEN_INTERNAL",
            "--out": str(tmp_file),
            "--outform": "KLE_RAW",
            "--text": "",
        }
        if ergogen_filter:
            args["--ergogen-filter"] = ergogen_filter
        p = self._run_subprocess(package_path, package_name, args)
        p.communicate()
        assert p.returncode == 0

        with open(f"{data_dir}/ergogen-layouts/{example}-reference.json", "r") as f:
            reference = json.load(f)

        with open(tmp_file, "r") as f:
            assert json.load(f) == reference

    def test_ergogen_file_convert_direct_yaml(
        self, request, tmpdir, package_path, package_name
    ) -> None:
        test_dir = request.fspath.dirname
        data_dir = f"{test_dir}/data"
        example = "absolem-simple"
        shutil.copy(f"{data_dir}/ergogen-layouts/{example}-points.yaml", tmpdir)
        layout_file = f"{tmpdir}/{example}-points.yaml"
        tmp_file = Path(layout_file).with_suffix(".json.tmp")
        args = {
            "--in": layout_file,
            "--inform": "ERGOGEN_INTERNAL",
            "--out": str(tmp_file),
            "--outform": "KLE_RAW",
            "--text": "",
        }
        p = self._run_subprocess(package_path, package_name, args)
        p.communicate()
        assert p.returncode == 0

        with open(f"{data_dir}/ergogen-layouts/{example}-reference.json", "r") as f:
            reference = json.load(f)

        with open(tmp_file, "r") as f:
            assert json.load(f) == reference

    @pytest.mark.parametrize("form", ["KLE_RAW", "KLE_INTERNAL"])
    def test_convertion_not_needed(
        self, package_path, package_name, tmpdir, form
    ) -> None:
        p = self._run_subprocess(
            package_path,
            package_name,
            {
                "--in": f"{tmpdir}/in.json",
                "--inform": form,
                "--out": f"{tmpdir}/out.json",
                "--outform": form,
                "--text": "",
            },
        )
        outs, _ = p.communicate()
        assert p.returncode == 1
        assert outs == "Output format equal input format, nothing to do...\n"


def test_utf8_label(request) -> None:
    test_dir = request.fspath.dirname
    data_dir = f"{test_dir}/data"
    layout_path = f"{data_dir}/kle-layouts/one-key-with-utf-8-label.json"

    logger.info(f"Preferred encoding: {locale.getpreferredencoding()}")
    if sys.version_info >= (3, 11):
        logger.info(f"Encoding: {locale.getencoding()}")

    keyboard = get_keyboard_from_file(layout_path)
    assert len(keyboard.keys) == 1
    assert keyboard.keys[0].labels == ["😊"]


def test_illegal_key_label_position() -> None:
    k = Key()
    with pytest.raises(RuntimeError, match="Illegal key label index"):
        k.set_label(KEY_MAX_LABELS, "Enter")


def __get_layout_classification_parameters():
    test_params = []
    kle_presets = [
        # some standard layouts from keyboard-layout-editor.com
        (
            "ansi-104-big-ass-enter",
            [KeyboardTag.ROW_STAGGERED, KeyboardTag.WITH_UNRECOGNIZED_KEY_SHAPE],
        ),
        ("ansi-104", [KeyboardTag.ROW_STAGGERED]),
        ("atreus", [KeyboardTag.OTHER]),
        ("ergodox", [KeyboardTag.OTHER]),
        ("iso-105", [KeyboardTag.ROW_STAGGERED, KeyboardTag.ISO]),
        ("kinesis-advantage", [KeyboardTag.OTHER]),
        ("planck", [KeyboardTag.ORTHOLINEAR]),
        # and column stagger example:
        ("jiran", [KeyboardTag.COLUMN_STAGGERED]),
    ]
    for f, expected in kle_presets:
        param = pytest.param(
            f"./data/kle-layouts/{f}.json",
            expected,
            id=f,
        )
        test_params.append(param)

    return test_params


@pytest.mark.parametrize(
    "layout_file,expected_tags", __get_layout_classification_parameters()
)
def test_layout_classification(layout_file, expected_tags, request) -> None:
    test_dir = request.fspath.dirname

    with open(Path(test_dir) / layout_file, "r") as f:
        layout = json.load(f)
        result = get_keyboard(layout)
        tags = layout_classification(result)
        assert tags == expected_tags


@pytest.mark.parametrize(
    "layout_file,expected_spacing",
    [
        # Layouts with custom explicit spacing
        ("./data/kle-layouts/test-custom-spacing.json", (20.5, 21.0)),
        ("./data/kle-layouts/test-custom-spacing-internal.json", (20.5, 21.0)),
        # Layout without spacing fields (should return None)
        ("./data/kle-layouts/test-no-spacing-internal.json", None),
        # Layout with default spacing (19.05, 19.05) - should return it since it's explicit
        ("./data/kle-layouts/ansi-104-internal.json", (19.05, 19.05)),
        # Layout with invalid spacing definition (should fallback to None)
        ("./data/kle-layouts/test-no-spacing-illegal.json", None),
    ],
)
def test_get_explicit_spacing_from_file(layout_file, expected_spacing, request) -> None:
    test_dir = request.fspath.dirname
    layout_path = Path(test_dir) / layout_file

    result = get_explicit_spacing_from_file(layout_path)
    assert result == expected_spacing
