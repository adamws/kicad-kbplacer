import json
import pytest

from pathlib import Path

try:
    from kbplacer.kle_serial import parse, Keyboard
except:
    pass


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
        ([[{"a":7},"\n\n\n\nx"]],   (10 * [None]) + ["x"]), # fron-center
        ([[{"a":3},"\n\n\n\n\nx"]], (11 * [None]) + ["x"]), # front-right
        ([[{"a":0},"x\nx\nx\nx\nx\nx\nx\nx\nx\nx\nx\nx"]], (12 * ["x"])) # all at once
    ],
    # fmt: on
)
def test_labels(layout, expected) -> None:
    result = parse(layout)
    assert result.keys[0].labels == expected


def get_reference(path: str):
    reference_dict = {}
    reference: Keyboard = None
    with open(path, "r") as f:
        layout: str = f.read()
        reference_dict = json.loads(layout)
        reference: Keyboard = Keyboard.from_json(layout)
        return reference, reference_dict


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
            f"../examples/{e}/kle.json", f"../examples/{e}/kle-internal.json", id=e
        )
        test_params.append(param)

    return test_params


@pytest.mark.parametrize("layout_file,reference_file", __get_parameters())
def test_with_references(layout_file, reference_file, request) -> None:
    test_dir = request.fspath.dirname

    reference, reference_dict = get_reference(Path(test_dir) / reference_file)

    with open(Path(test_dir) / layout_file, "r") as f:
        layout = json.load(f)
        result = parse(layout)
        assert result == reference
        assert json.loads(result.to_json()) == reference_dict
