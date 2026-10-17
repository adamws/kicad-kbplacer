# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for pcb2layout tool.

Most of the tests use kbplacer to create PCB out of a layout, then use
pcb2layout to recover the layout from that PCB and compare both layouts
by key positions (in mm, as kbplacer would place footprints), orientations,
sizes and (optionally) matrix annotations. Additionally, tool's own
verification (PCB re-created from recovered layout) must give full score.
"""

from __future__ import annotations

import copy
import json
import math
import os
import random
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

pcbnew = pytest.importorskip("pcbnew")

TOOLS_DIR = Path(__file__).parent.parent
PROJECT_ROOT = TOOLS_DIR.parent
for path in (TOOLS_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pcb2layout  # noqa: E402

from kbplacer.board_modifier import KICAD_VERSION  # noqa: E402
from kbplacer.kle_serial import (  # noqa: E402
    Keyboard,
    MatrixAnnotatedKeyboard,
    get_keyboard,
    get_keyboard_from_file,
)

TEST_FOOTPRINTS = PROJECT_ROOT / "tests" / "data" / "footprints" / "tests.pretty"
EXAMPLES = PROJECT_ROOT / "examples"
KLE_LAYOUTS = PROJECT_ROOT / "tests" / "data" / "kle-layouts"
VIA_LAYOUTS = PROJECT_ROOT / "tests" / "data" / "via-layouts"
TEST_LAYOUTS = Path(__file__).parent / "data" / "pcb2layout"

SWITCH_WIDTHS = [1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75, 3, 6, 6.25, 7]
STABILIZER_WIDTHS = [2, 6.25, 7]

Pose = Tuple

HYBRID = "keyswitch_cherrymx_hotswap_1u_rotary_encoder_ec12"

# Alps EC11 encoder footprint (also source of HYBRID one) can't be loaded
# by KiCad older than 10.0
requires_encoder_footprint = pytest.mark.skipif(
    KICAD_VERSION < (10, 0, 0),
    reason="Encoder footprint not recognized by KiCad older than 10.0",
)
ENCODERS = pytest.param(
    TEST_LAYOUTS / "encoders.json", marks=requires_encoder_footprint
)


def _copy_footprint(source: Path, destination_dir: Path, name: str) -> None:
    content = source.read_text()
    content = re.sub(
        r'^\((module|footprint) "?[^"\s]+"?',
        lambda m: f'({m.group(1)} "{name}"',
        content,
        count=1,
    )
    (destination_dir / f"{name}.kicad_mod").write_text(content)


@pytest.fixture(scope="session")
def library(tmp_path_factory) -> Path:
    """Footprint library with variable width switch & stabilizer footprints"""
    lib = tmp_path_factory.mktemp("footprints") / "pcb2layout.pretty"
    lib.mkdir()
    mx = TEST_FOOTPRINTS / "SW_Cherry_MX_PCB_1.00u.kicad_mod"
    for width in SWITCH_WIDTHS:
        _copy_footprint(mx, lib, f"SW_Cherry_MX_PCB_{width:.2f}u")
    _copy_footprint(mx, lib, "SW_Cherry_MX_PCB_ISOEnter")
    stab = TEST_FOOTPRINTS / "Stabilizer_Cherry_MX_2.00u.kicad_mod"
    for width in STABILIZER_WIDTHS:
        _copy_footprint(stab, lib, f"Stabilizer_Cherry_MX_{width:.2f}u")
    for name in [
        "Kailh_socket_PG1350_optional_reversible",
        "D_SOD-323F",
        "RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm_CircularMountingHoles",
    ]:
        _copy_footprint(TEST_FOOTPRINTS / f"{name}.kicad_mod", lib, name)
    # footprint accepting either key switch or encoder (as in Corne keyboard)
    _copy_footprint(
        TEST_FOOTPRINTS
        / "RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm_CircularMountingHoles.kicad_mod",
        lib,
        HYBRID,
    )
    return lib


def mx_switch(library: Path) -> str:
    return f"{library}:SW_Cherry_MX_PCB_{{:.2f}}u"


def hotswap_switch(library: Path) -> str:
    return f"{library}:Kailh_socket_PG1350_optional_reversible"


def annotate_sequentially(keyboard: Keyboard) -> Keyboard:
    """Make layout acceptable for kbplacer's PCB creation mode which requires
    matrix annotations"""
    result = copy.deepcopy(keyboard)
    column = 0
    for key in result.keys:
        key.labels = []
        key.textColor = []
        key.textSize = []
        if key.decal:
            continue
        key.set_label(MatrixAnnotatedKeyboard.MATRIX_COORDINATES_LABEL, f"0,{column}")
        column += 1
    return result


def generate_pcb(
    library: Path,
    keyboard: Keyboard,
    directory: Path,
    *,
    switch: Optional[str] = None,
    encoder: Optional[str] = None,
    stabilizers: bool = True,
    args: Optional[List[str]] = None,
) -> Path:
    layout_path = directory / "layout.json"
    layout_path.write_text(keyboard.to_json())
    pcb_path = directory / "keyboard.kicad_pcb"
    command = [
        sys.executable,
        "-m",
        "kbplacer",
        "--pcb-file",
        str(pcb_path),
        "--layout",
        str(layout_path),
        "--create-pcb-file",
        "--switch-footprint",
        switch or mx_switch(library),
        "--diode-footprint",
        f"{library}:D_SOD-323F",
        "--encoder-footprint",
        encoder
        or f"{library}:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm_CircularMountingHoles",
    ]
    if stabilizers:
        command += [
            "--stabilizer-footprint",
            f"{library}:Stabilizer_Cherry_MX_{{:.2f}}u",
        ]
    else:
        command += ["--no-stabilizers"]
    command += args or []
    result = subprocess.run(
        command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert pcb_path.is_file()
    return pcb_path


def reverse(pcb_path: Path, *args: str) -> Keyboard:
    output = pcb_path.with_suffix(".out.json")
    assert pcb2layout.main(["-i", str(pcb_path), "-o", str(output), "-f", *args]) == 0
    with open(output, "r", encoding="utf-8") as f:
        return get_keyboard(json.load(f))


def _round(value: float, digits: int = 2) -> float:
    return round(value, digits) + 0.0


def layout_poses(keyboard: Keyboard, *, labels: bool) -> List[Pose]:
    """Key centers (in mm, using kbplacer formulas) with orientation, size,
    switch mount and optional matrix label"""
    sx, sy = keyboard.meta.spacing_x, keyboard.meta.spacing_y
    if labels:
        annotated = MatrixAnnotatedKeyboard.from_keyboard(copy.deepcopy(keyboard))
        annotated.collapse()
        keys = list(annotated.key_iterator(ignore_alternative=False))
    else:
        keys = keyboard.keys
    poses = []
    for key in keys:
        if key.decal:
            continue
        center = (sx * (key.x + key.width / 2), sy * (key.y + key.height / 2))
        if key.rotation_angle:
            center = pcb2layout.rotate_point(
                center, (sx * key.rotation_x, sy * key.rotation_y), key.rotation_angle
            )
        orientation = _round(key.rotation_angle + key.switchRotation) % 360
        if key.width == key.height:
            # square key rotated by multiple of 90 looks the same
            orientation = orientation % 90
        elif key.width2 == key.width and key.height2 == key.height:
            orientation = orientation % 180
        size = (key.width, key.height, key.width2, key.height2, key.x2, key.y2)
        label = key.get_label(0) if labels else None
        poses.append((center, orientation, size, key.sm, label))
    min_x = min(p[0][0] for p in poses)
    min_y = min(p[0][1] for p in poses)
    result = []
    for center, *rest in poses:
        result.append((_round(center[0] - min_x), _round(center[1] - min_y), *rest))
    return sorted(result, key=lambda p: (p[1], p[0], str(p)))


def match_layouts(
    expected: Keyboard, actual: Keyboard, *, labels: bool, tolerance: float = 0.02
) -> Tuple[List[Pose], List[Pose]]:
    """Pair keys of both layouts, returns unmatched expected and actual keys"""
    unmatched = layout_poses(actual, labels=labels)
    missing = []
    for e in layout_poses(expected, labels=labels):
        for i, a in enumerate(unmatched):
            if (
                e[2:] == a[2:]
                and abs(e[0] - a[0]) <= tolerance
                and abs(e[1] - a[1]) <= tolerance
            ):
                del unmatched[i]
                break
        else:
            missing.append(e)
    return missing, unmatched


def assert_same_layout(expected: Keyboard, actual: Keyboard, *, labels: bool) -> None:
    missing, unexpected = match_layouts(expected, actual, labels=labels)
    assert (
        not missing and not unexpected
    ), f"\nexpected but not found: {missing}\nfound but not expected: {unexpected}"


def footprint_poses(pcb_path: Path) -> List[Pose]:
    board = pcbnew.LoadBoard(str(pcb_path))
    poses = []
    for f in board.GetFootprints():
        if not re.match(r"^(SW|ST)\d", f.GetReference()):
            continue
        x, y = pcbnew.ToMM(f.GetPosition().x), pcbnew.ToMM(f.GetPosition().y)
        orientation = _round(f.GetOrientationDegrees() % 360, 1) % 360
        name = str(f.GetFPID().GetLibItemName())
        poses.append((x, y, orientation, name))
    min_x = min(p[0] for p in poses)
    min_y = min(p[1] for p in poses)
    return sorted(
        (_round(x - min_x, 1), _round(y - min_y, 1), o, n) for x, y, o, n in poses
    )


def roundtrip(
    library: Path,
    keyboard: Keyboard,
    tmp_path: Path,
    *,
    labels: bool,
    switch: Optional[str] = None,
    stabilizers: bool = True,
    kbplacer_args: Optional[List[str]] = None,
    tool_args: Optional[List[str]] = None,
) -> Keyboard:
    original_dir = tmp_path / "original"
    original_dir.mkdir()
    pcb = generate_pcb(
        library,
        keyboard,
        original_dir,
        switch=switch,
        stabilizers=stabilizers,
        args=kbplacer_args,
    )
    tool_args = list(tool_args or []) + ["--verify-min-score", "100"]
    if labels:
        tool_args.append("--matrix-labels")
    result = reverse(pcb, *tool_args)
    assert_same_layout(keyboard, result, labels=labels)
    return result


def load(path: Path, *, annotate: bool = False) -> Keyboard:
    keyboard = get_keyboard_from_file(str(path))
    if isinstance(keyboard, MatrixAnnotatedKeyboard):
        keys = keyboard.keys + keyboard.alternative_keys
        keyboard = Keyboard(meta=keyboard.meta, keys=keys)
    if annotate:
        keyboard = annotate_sequentially(keyboard)
    return keyboard


def rewrite_pcb(pcb_path: Path, replacements: List[Tuple[str, str]]) -> None:
    content = pcb_path.read_text()
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)
    pcb_path.write_text(content)


# Layouts which are expected to be fully recoverable when switch footprint
# names reveal key size. Some other layouts in test data use key sizes which
# kbplacer can't express with footprint choice (e.g. 1x1.5U vertical keys
# without stabilizers, 0.75U high keys, stepped keys) so are not used here.
VIA_ANNOTATED = [
    EXAMPLES / "2x2" / "kle-annotated.json",
    EXAMPLES / "2x3-rotations" / "kle-annotated.json",
    EXAMPLES / "3x2-sizes" / "kle-annotated.json",
    EXAMPLES / "2x2-with-alternative-layout" / "via.json",
    VIA_LAYOUTS / "0_sixty.json",
    VIA_LAYOUTS / "wt60_a.json",
    VIA_LAYOUTS / "wt60_d.json",
    VIA_LAYOUTS / "arya.json",
    ENCODERS,
]

KLE = [
    KLE_LAYOUTS / "ansi-104.json",
    KLE_LAYOUTS / "iso-105.json",
    KLE_LAYOUTS / "jiran.json",
    KLE_LAYOUTS / "planck.json",
]

# Layouts recoverable with size agnostic switch footprints (hotswap sockets),
# key sizes are inferred from stabilizers and neighbouring keys
HOTSWAP = [
    (KLE_LAYOUTS / "ansi-104.json", True),
    (KLE_LAYOUTS / "iso-105.json", True),
    (KLE_LAYOUTS / "planck.json", True),
    (VIA_LAYOUTS / "0_sixty.json", False),
]


def _id(path: Path) -> str:
    return f"{path.parent.name}-{path.stem}"


@pytest.mark.parametrize("layout", VIA_ANNOTATED, ids=_id)
def test_via_annotated_with_named_footprints(library, layout, tmp_path) -> None:
    roundtrip(library, load(layout), tmp_path, labels=True)


@pytest.mark.parametrize("layout", KLE, ids=_id)
def test_kle_with_named_footprints(library, layout, tmp_path) -> None:
    roundtrip(library, load(layout, annotate=True), tmp_path, labels=True)


@pytest.mark.parametrize(
    "layout,annotate", HOTSWAP, ids=lambda v: _id(v) if isinstance(v, Path) else ""
)
def test_hotswap_footprints_with_stabilizers(
    library, layout, annotate, tmp_path
) -> None:
    roundtrip(
        library,
        load(layout, annotate=annotate),
        tmp_path,
        labels=True,
        switch=hotswap_switch(library),
    )


def test_hotswap_footprints_without_stabilizers(library, tmp_path) -> None:
    # without stabilizers, wide keys are recognized only when closing gaps
    # on both sides (here: space bar between two 1U keys)
    layout = TEST_LAYOUTS / "ortho-with-space.json"
    roundtrip(
        library,
        load(layout),
        tmp_path,
        labels=True,
        switch=hotswap_switch(library),
        stabilizers=False,
    )


@pytest.mark.parametrize(
    "layout", [EXAMPLES / "2x3-rotations" / "kle-annotated.json"], ids=_id
)
@pytest.mark.parametrize("orientation", ["90", "180", "270"])
@pytest.mark.parametrize("side", ["FRONT", "BACK"])
def test_switch_orientation_and_side(
    library, layout, orientation, side, tmp_path
) -> None:
    roundtrip(
        library,
        load(layout),
        tmp_path,
        labels=True,
        kbplacer_args=["--switch", f"SW{{}} {orientation} {side}"],
    )


def test_explicit_switch_orientation(library, tmp_path) -> None:
    # all keys rotated by 90 degrees, without hint this can't be distinguished
    # from rotated switches of non-rotated keys
    layout = EXAMPLES / "3x2-sizes" / "kle-annotated.json"
    keyboard = load(layout)
    pcb = generate_pcb(library, keyboard, tmp_path, args=["--switch", "SW{} 90 FRONT"])
    result = reverse(pcb, "--matrix-labels", "--switch-orientation", "90")
    assert_same_layout(keyboard, result, labels=True)


@pytest.mark.parametrize(
    "layout,spacing",
    [
        (EXAMPLES / "2x3-rotations" / "kle-annotated.json", (18, 17)),
        (EXAMPLES / "2x3-rotations" / "kle-annotated.json", (19.05, 18)),
        (KLE_LAYOUTS / "planck.json", (18, 17)),
        (KLE_LAYOUTS / "planck.json", (19, 19)),
        # split layout with rotated halves designed for square spacing,
        # with non-square spacing footprints would overlap
        (VIA_LAYOUTS / "arya.json", (18, 18)),
        (VIA_LAYOUTS / "arya.json", (19, 19)),
    ],
    ids=lambda v: _id(v) if isinstance(v, Path) else f"{v[0]}x{v[1]}",
)
def test_key_spacing(library, layout, spacing, tmp_path) -> None:
    keyboard = load(layout, annotate=layout.parent == KLE_LAYOUTS)
    keyboard.meta.spacing_x, keyboard.meta.spacing_y = spacing
    result = roundtrip(library, keyboard, tmp_path, labels=True)
    assert (result.meta.spacing_x, result.meta.spacing_y) == spacing


def test_key_spacing_from_argument(library, tmp_path) -> None:
    keyboard = load(EXAMPLES / "2x2" / "kle-annotated.json")
    keyboard.meta.spacing_x, keyboard.meta.spacing_y = 18, 17
    pcb = generate_pcb(library, keyboard, tmp_path)
    # with wrong spacing positions are scaled
    result = reverse(pcb, "--matrix-labels", "--key-distance", "9 8.5")
    assert (result.meta.spacing_x, result.meta.spacing_y) == (9, 8.5)
    assert [(k.x, k.y) for k in result.keys] == [(0, 0), (2, 0), (0, 2), (2, 2)]


@requires_encoder_footprint
def test_encoder_adjustment(library, tmp_path) -> None:
    keyboard = load(TEST_LAYOUTS / "encoders.json")
    roundtrip(
        library,
        keyboard,
        tmp_path,
        labels=True,
        kbplacer_args=["--encoder-adjustment", "-7.5 -2.5"],
        tool_args=["--encoder-adjustment", "-7.5 -2.5"],
    )


@pytest.mark.parametrize(
    "layout",
    [
        EXAMPLES / "2x3-rotations" / "kle-annotated.json",
        VIA_LAYOUTS / "0_sixty.json",
        KLE_LAYOUTS / "ansi-104.json",
    ],
    ids=_id,
)
def test_pcb_roundtrip(library, layout, tmp_path) -> None:
    """PCB -> layout -> PCB, footprints should end up in the same places"""
    keyboard = load(layout, annotate=layout.parent == KLE_LAYOUTS)
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first = generate_pcb(library, keyboard, tmp_path / "first")
    result = reverse(first, "--matrix-labels")
    second = generate_pcb(library, result, tmp_path / "second")
    assert footprint_poses(first) == footprint_poses(second)


def test_examples_boards() -> None:
    """Boards created with kbplacer which are part of examples"""
    rotations = EXAMPLES / "2x3-rotations" / "kle-annotated.json"
    for name, layout in [
        ("2x2", EXAMPLES / "2x2" / "kle-annotated.json"),
        ("2x3-rotations", rotations),
        ("2x3-rotations-double-diodes", rotations),
        ("2x3-rotations-custom-diode-with-track", rotations),
        ("2x3-rotations-custom-diode-with-track-and-complex-footprint", rotations),
        ("3x2-sizes", EXAMPLES / "3x2-sizes" / "kle-annotated.json"),
        (
            "2x2-with-alternative-layout",
            EXAMPLES / "2x2-with-alternative-layout" / "via.json",
        ),
    ]:
        board = pcbnew.LoadBoard(str(EXAMPLES / name / "keyboard-after.kicad_pcb"))
        opts = pcb2layout.Options(matrix_labels=True)
        result = pcb2layout.reverse_engineer(board, opts)
        assert_same_layout(load(layout), result, labels=True)
        verification = pcb2layout.verify_layout(board, result, opts)
        assert verification.success, verification.summary()


def test_matrix_with_unrecognized_net_names(library, tmp_path) -> None:
    keyboard = load(EXAMPLES / "3x2-sizes" / "kle-annotated.json")
    pcb = generate_pcb(library, keyboard, tmp_path)
    rewrite_pcb(pcb, [(r'"ROW(\d+)"', r'"KR\1"'), (r'"COL(\d+)"', r'"KC\1"')])

    # rows recognized by diodes (COL2ROW)
    result = reverse(pcb, "--matrix-labels")
    assert_same_layout(keyboard, result, labels=True)

    # rows and columns swapped
    result = reverse(pcb, "--matrix-labels", "--diode-side", "column")
    labels = sorted(k.labels[0] for k in result.keys)
    swapped = sorted(",".join(reversed(k.labels[0].split(","))) for k in keyboard.keys)
    assert labels == swapped

    # explicit patterns
    result = reverse(
        pcb, "--matrix-labels", "--row-pattern", "KR{}", "--column-pattern", "KC{}"
    )
    assert_same_layout(keyboard, result, labels=True)


def test_matrix_with_non_numeric_net_names(library, tmp_path) -> None:
    keyboard = load(EXAMPLES / "3x2-sizes" / "kle-annotated.json")
    pcb = generate_pcb(library, keyboard, tmp_path)
    names = {"ROW0": "TOP", "ROW1": "MIDDLE", "ROW2": "BOTTOM"}
    names |= {"COL0": "LEFT", "COL1": "CENTER", "COL2": "RIGHT"}
    rewrite_pcb(pcb, [(f'"{k}"', f'"{v}"') for k, v in names.items()])

    result = reverse(pcb, "--matrix-labels")
    # indexes are assigned by net names order:
    rows = {"BOTTOM": "0", "MIDDLE": "1", "TOP": "2"}
    columns = {"CENTER": "0", "LEFT": "1", "RIGHT": "2"}
    expected = copy.deepcopy(keyboard)
    for key in expected.keys:
        row, column = key.labels[0].split(",")
        key.labels[0] = f"{rows[names['ROW' + row]]},{columns[names['COL' + column]]}"
    assert_same_layout(expected, result, labels=True)


def test_explicit_annotation(library, tmp_path) -> None:
    keyboard = load(KLE_LAYOUTS / "planck.json", annotate=True)
    pcb = generate_pcb(library, keyboard, tmp_path)
    result = reverse(pcb, "--explicit-annotation")
    board = pcbnew.LoadBoard(str(pcb))

    def _center(key) -> Tuple[float, float]:
        return (19.05 * (key.x + key.width / 2), 19.05 * (key.y + key.height / 2))

    origin_key = result.keys[0]
    origin = board.FindFootprintByReference(f"SW{origin_key.labels[10]}").GetPosition()
    for key in result.keys:
        footprint = board.FindFootprintByReference(f"SW{key.labels[10]}")
        position = footprint.GetPosition()
        dx = pcbnew.ToMM(position.x - origin.x)
        dy = pcbnew.ToMM(position.y - origin.y)
        cx, cy = _center(key)
        ox, oy = _center(origin_key)
        assert math.isclose(dx, cx - ox, abs_tol=0.01)
        assert math.isclose(dy, cy - oy, abs_tol=0.01)


def test_switch_detection(library, tmp_path) -> None:
    keyboard = load(EXAMPLES / "3x2-sizes" / "kle-annotated.json")
    pcb = generate_pcb(library, keyboard, tmp_path)
    # use non-standard references
    rewrite_pcb(pcb, [(r'"Reference" "SW(\d+)"', r'"Reference" "K\1"')])
    # add reset button which should not be considered a key
    board = pcbnew.LoadBoard(str(pcb))
    button = pcbnew.FootprintLoad(str(library), "D_SOD-323F")
    button.SetFPID(pcbnew.LIB_ID("Button_Switch_SMD", "SW_SPST_TL3342"))
    button.SetReference("SW1")
    board.Add(button)
    pcbnew.SaveBoard(str(pcb), board)

    result = reverse(pcb, "--matrix-labels")
    assert_same_layout(keyboard, result, labels=True)

    # selecting by pattern
    result = reverse(pcb, "--matrix-labels", "--switch-pattern", "K{}")
    assert_same_layout(keyboard, result, labels=True)

    # selecting by footprint name
    result = reverse(pcb, "--switch-footprint-regex", "1\\.00u")
    assert len(result.keys) == 4


@pytest.mark.parametrize(
    "width_source,expected_widths",
    [
        # stabilizer footprint name gives minimal width, the rest is
        # fitted between neighbouring keys:
        ("auto", 6 * [1] + [1, 1, 3, 1]),
        ("neighbors", 6 * [1] + [1, 1, 3, 1]),
        # only stabilizer footprint name:
        ("name", 6 * [1] + [1, 1, 2, 1]),
        ("none", 10 * [1]),
    ],
)
def test_width_source(library, width_source, expected_widths, tmp_path) -> None:
    keyboard = load(TEST_LAYOUTS / "ortho-with-space.json")
    pcb = generate_pcb(library, keyboard, tmp_path, switch=hotswap_switch(library))
    result = reverse(pcb, "--width-source", width_source)
    assert [k.width for k in result.keys] == expected_widths


def test_alternatives_in_place(library, tmp_path) -> None:
    keyboard = load(EXAMPLES / "2x2-with-alternative-layout" / "via.json")
    pcb = generate_pcb(library, keyboard, tmp_path)
    displaced = reverse(pcb, "--matrix-labels")
    in_place = reverse(pcb, "--matrix-labels", "--alternatives-in-place")
    assert max(k.y for k in displaced.keys) == 3
    assert max(k.y for k in in_place.keys) == 1
    assert_same_layout(keyboard, in_place, labels=True)


def test_output_format(library, tmp_path) -> None:
    keyboard = load(EXAMPLES / "2x3-rotations" / "kle-annotated.json")
    pcb = generate_pcb(library, keyboard, tmp_path)
    kle = tmp_path / "kle.json"
    internal = tmp_path / "internal.json"
    assert pcb2layout.main(["-i", str(pcb), "-o", str(kle), "--matrix-labels"]) == 0
    args = ["-i", str(pcb), "-o", str(internal), "--format", "internal"]
    assert pcb2layout.main(args + ["--matrix-labels"]) == 0
    with open(kle) as f:
        kle_data = json.load(f)
    with open(internal) as f:
        internal_data = json.load(f)
    assert kle_data == [
        ["0,0"],
        ["1,0"],
        [{"r": 15, "rx": 1, "ry": 2, "y": -2, "w": 2}, "0,1"],
        ["1,1", "1,2"],
    ]
    assert get_keyboard(kle_data) == get_keyboard(internal_data)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("SW_Cherry_MX_PCB_1.00u", 1),
        ("SW_Cherry_MX_1.25u_PCB", 1.25),
        ("MX-2.25U", 2.25),
        ("SW_MX_6.25u", 6.25),
        ("Stabilizer_Cherry_MX_2u", 2),
        ("Kailh_socket_PG1350_optional_reversible", None),
        ("SW_Cherry_MX_ISOEnter", None),
        ("MX_1,5u", 1.5),
    ],
)
def test_width_from_name(name, expected) -> None:
    assert pcb2layout.width_from_name(name) == expected


def _row(*keys: Tuple[float, List[float]]) -> List[pcb2layout.PlacedKey]:
    return [
        pcb2layout.PlacedKey(
            switch=None,  # type: ignore
            angle=0,
            switch_rotation=0,
            cluster=0,
            local=(0, 0),
            center_u=(center, 0),
            allowed_widths=widths,
            width_evidence=len(widths) == 1 or min(widths) >= 2,
        )
        for center, widths in keys
    ]


def test_solve_row_widths() -> None:
    any_width = pcb2layout.UNSTABILIZED_WIDTHS
    stabilized = pcb2layout.STABILIZED_WIDTHS
    # ANSI bottom row with stabilized space bar
    centers = [0.625, 1.875, 3.125, 6.875, 10.625, 11.875, 13.125, 14.375]
    row = _row(*[(c, stabilized if c == 6.875 else any_width) for c in centers])
    assert pcb2layout.solve_row_widths(row, 0) == [1.25] * 3 + [6.25] + [1.25] * 4
    # backspace at the end of the row
    row = _row((11.5, any_width), (12.5, any_width), (14, stabilized))
    assert pcb2layout.solve_row_widths(row, 11) == [1, 1, 2]
    # gaps between keys are kept when keys can't be wider
    row = _row((0.5, any_width), (2.5, any_width), (3.5, any_width))
    assert pcb2layout.solve_row_widths(row, 0) == [1, 1, 1]
    # right bound
    row = _row((0.5, any_width), (1.875, any_width))
    assert pcb2layout.solve_row_widths(row, 0, 2.5) == [1, 1.25]


def test_guess_spacing() -> None:
    assert pcb2layout._guess_spacing([19.05, 19.05, 9.525, 9.525, 9.525]) == 19.05
    assert pcb2layout._guess_spacing([18.01, 17.99, 18.0, 36.0]) == 18.0
    assert pcb2layout._guess_spacing([15.5, 15.5, 31.0]) == 15.5
    assert pcb2layout._guess_spacing([]) is None


@pytest.mark.parametrize(
    "name,expected",
    [
        (HYBRID, True),
        ("SW_MX_Hotswap_EC11_combo", True),
        ("Choc_Encoder_EC12", True),
        ("RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm", False),
        ("RotaryEncoder_EC11", False),
        ("SW_Cherry_MX_PCB_1.00u", False),
    ],
)
def test_is_hybrid_name(name, expected) -> None:
    assert pcb2layout.is_hybrid_name(name) == expected


@requires_encoder_footprint
def test_hybrid_encoders(library, tmp_path) -> None:
    keyboard = load(TEST_LAYOUTS / "encoders.json")
    pcb = generate_pcb(library, keyboard, tmp_path, encoder=f"{library}:{HYBRID}")
    verify = ["--verify-min-score", "100"]

    result = reverse(pcb, "--matrix-labels", "--hybrid-encoders", "encoder", *verify)
    assert_same_layout(keyboard, result, labels=True)

    as_switches = copy.deepcopy(keyboard)
    for key in as_switches.keys:
        key.sm = ""
    result = reverse(pcb, "--matrix-labels", "--hybrid-encoders", "switch", *verify)
    assert_same_layout(as_switches, result, labels=True)

    # default: switch with encoder as alternative layout choice
    result = reverse(pcb, "--matrix-labels", *verify)
    choices = sorted(
        (k.get_label(0), k.get_label(8), k.sm) for k in result.keys if k.get_label(8)
    )
    encoders = [k.get_label(0) for k in keyboard.keys if k.sm == "rot_ec11"]
    assert len(encoders) == 4
    # each encoder position becomes layout option with two choices
    groups = {label: g for g, label in enumerate(sorted(encoders))}
    assert sorted(choices) == sorted(
        (label, f"{groups[label]},{choice}", sm)
        for label in encoders
        for choice, sm in [(0, ""), (1, "rot_ec11")]
    )
    annotated = MatrixAnnotatedKeyboard.from_keyboard(copy.deepcopy(result))
    annotated.collapse()
    encoders = [k for k in annotated.alternative_keys if k.sm == "rot_ec11"]
    defaults = {(k.x, k.y) for k in annotated.keys if k.get_label(8)}
    assert {(k.x, k.y) for k in encoders} == defaults

    # without matrix labels alternatives overlap switches
    result = reverse(pcb, *verify)
    assert len(result.keys) == len(keyboard.keys) + len(encoders)
    switches = {(k.x, k.y) for k in result.keys if k.sm == ""}
    assert {(k.x, k.y) for k in result.keys if k.sm == "rot_ec11"} <= switches
    assert all(not any(k.labels) for k in result.keys)


def _shuffle_switch_references(pcb_path: Path) -> None:
    board = pcbnew.LoadBoard(str(pcb_path))
    switches = [
        f for f in board.GetFootprints() if re.match(r"^SW\d+$", f.GetReference())
    ]
    references = [f.GetReference() for f in switches]
    random.Random(1).shuffle(references)
    for footprint, reference in zip(switches, references):
        footprint.SetReference(reference)
    pcbnew.SaveBoard(str(pcb_path), board)


@pytest.mark.parametrize(
    "layout",
    [
        VIA_LAYOUTS / "arya.json",
        EXAMPLES / "2x2-with-alternative-layout" / "via.json",
        ENCODERS,
    ],
    ids=_id,
)
@pytest.mark.parametrize("labels", [True, False], ids=["labels", "no-labels"])
def test_verify_ignores_annotations_and_origin(
    library, layout, labels, tmp_path
) -> None:
    keyboard = load(layout)
    pcb = generate_pcb(
        library, keyboard, tmp_path, args=["--layout-offset", "37.3 -12.1"]
    )
    _shuffle_switch_references(pcb)
    board = pcbnew.LoadBoard(str(pcb))
    opts = pcb2layout.Options(matrix_labels=labels)
    result = pcb2layout.reverse_engineer(board, opts)
    verification = pcb2layout.verify_layout(board, result, opts)
    assert verification.success, verification.summary()
    assert verification.score == 100
    assert (
        verification.original
        == verification.generated
        == len([f for f in board.GetFootprints() if re.match(r"^SW", f.GetReference())])
    )


def test_verify_score(library, tmp_path) -> None:
    keyboard = load(KLE_LAYOUTS / "planck.json", annotate=True)
    pcb = generate_pcb(library, keyboard, tmp_path)
    board = pcbnew.LoadBoard(str(pcb))
    opts = pcb2layout.Options(matrix_labels=True)
    result = pcb2layout.reverse_engineer(board, opts)
    count = len(result.keys)

    result.keys[5].x += 0.25  # half way to match radius, half credit
    result.keys[7].switchRotation = 90  # orientation mismatch, half credit
    extra = copy.deepcopy(result.keys[0])
    extra.y -= 3
    result.keys.append(extra)  # not on original board
    del result.keys[20]  # missing on generated board

    verification = pcb2layout.verify_layout(board, result, opts)
    assert not verification.success
    assert verification.exact == count - 3
    assert len(verification.missing) == 1
    assert len(verification.extra) == 1
    assert sorted((m.distance, m.orientation) for m in verification.mismatches) == [
        (0, False),
        (4.7625, True),
    ]
    assert sorted(m.credit for m in verification.mismatches) == pytest.approx(
        [0.5, 0.5]
    )
    expected = math.floor(10000 * (count - 2) / (count + 1)) / 100
    assert verification.score == expected
    summary = verification.summary()
    assert f"Verification score: {expected:.2f}%" in summary
    assert "orientation differs" in summary
    assert "position off by 4.763 mm" in summary


def test_verify_unselected_switches(library, tmp_path) -> None:
    keyboard = load(EXAMPLES / "2x2" / "kle-annotated.json")
    pcb = generate_pcb(library, keyboard, tmp_path)
    board = pcbnew.LoadBoard(str(pcb))
    board.FindFootprintByReference("SW4").SetReference("X4")
    opts = pcb2layout.Options(switch_pattern="SW{}")
    result = pcb2layout.reverse_engineer(board, opts)
    assert len(result.keys) == 3
    verification = pcb2layout.verify_layout(board, result, opts)
    # footprints excluded by user's selection are reported but not scored
    assert verification.success, verification.summary()
    assert verification.unselected == ["X4"]
    assert "not selected but looking like switches (not scored): X4" in (
        verification.summary()
    )


def test_verification_layout() -> None:
    keyboard = get_keyboard(
        [
            [
                {"a": 0},
                "TOP,LEFT\n\n\n0,0",
                "TOP,RIGHT\n\n\n0,1",
                "",
                "BOTTOM,LEFT",
                "BOTTOM,LEFT",
                "\n\n\n4,1",
            ]
        ]
    )
    result = pcb2layout.verification_layout(keyboard)
    labels = [(k.get_label(0), k.get_label(8)) for k in result.keys]
    # numeric coordinates, missing or duplicated get unique ones
    assert labels == [
        ("0,0", "0,0"),
        ("0,1", "0,1"),
        ("2,0", None),
        ("1,0", None),
        ("2,1", None),
        ("2,2", "4,1"),  # layout option kept
    ]
    # input not modified
    assert keyboard.keys[0].get_label(0) == "TOP,LEFT"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    # keep inherited PYTHONPATH, it may be the way `pcbnew` is made importable
    pythonpath = [str(PROJECT_ROOT), os.environ.get("PYTHONPATH", "")]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, pythonpath))}
    return subprocess.run(
        [sys.executable, str(TOOLS_DIR / "pcb2layout.py"), *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_help() -> None:
    result = _run_cli("--help")
    assert result.returncode == 0
    assert "--matrix-labels" in result.stdout


def test_cli_stdout(library, tmp_path) -> None:
    keyboard = load(EXAMPLES / "2x2" / "kle-annotated.json")
    pcb = generate_pcb(library, keyboard, tmp_path)
    result = _run_cli("-i", str(pcb), "--matrix-labels")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [["0,0", "0,1"], ["1,0", "1,1"]]


def test_cli_errors(library, tmp_path) -> None:
    result = _run_cli("-i", str(tmp_path / "missing.kicad_pcb"))
    assert result.returncode == 1
    assert "does not exist" in result.stderr

    invalid = tmp_path / "invalid.kicad_pcb"
    invalid.write_text("not a board")
    result = _run_cli("-i", str(invalid))
    assert result.returncode == 1
    assert "Could not load" in result.stderr

    keyboard = load(EXAMPLES / "2x2" / "kle-annotated.json")
    pcb = generate_pcb(library, keyboard, tmp_path)
    output = tmp_path / "out.json"
    output.write_text("")
    result = _run_cli("-i", str(pcb), "-o", str(output))
    assert result.returncode == 1
    assert "already exist" in result.stderr
    assert _run_cli("-i", str(pcb), "-o", str(output), "--force").returncode == 0
    assert output.read_text().startswith("[")

    result = _run_cli("-i", str(pcb), "--switch-pattern", "NOTHING{}")
    assert result.returncode == 1
    assert "Could not find any key switch footprints" in result.stderr

    args = ["-i", str(pcb), "--matrix-labels", "--row-pattern", "ROW"]
    result = _run_cli(*args)
    assert result.returncode == 1
    assert "must contain '{}' placeholder" in result.stderr


def test_cli_verify(library, tmp_path) -> None:
    keyboard = load(EXAMPLES / "2x3-rotations" / "kle-annotated.json")
    pcb = generate_pcb(library, keyboard, tmp_path)
    result = _run_cli("-i", str(pcb), "--verify")
    assert result.returncode == 0, result.stderr
    assert "Verification score: 100.00%" in result.stderr

    # key distance only scales layout units, PCB re-created from it is the same
    result = _run_cli("-i", str(pcb), "--key-distance", "18 18", "--verify")
    assert result.returncode == 0, result.stderr
    assert "Verification score: 100.00%" in result.stderr

    # coarse grid snapping with huge tolerance moves keys
    args = ["-i", str(pcb), "--grid", "0.5", "--grid-tolerance", "0.25"]
    args += ["--verify-min-score", "99"]
    result = _run_cli(*args)
    assert result.returncode == pcb2layout.EXIT_LOW_SCORE, result.stderr
    assert "Verification score: 100.00%" not in result.stderr
    assert "mismatched" in result.stderr
