# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pcbnew
import pytest

from kbplacer.board_builder import BoardBuilder
from kbplacer.board_modifier import get_common_nets
from kbplacer.key_placer import KeyMatrix
from kbplacer.kle_serial import get_keyboard_from_file

from .conftest import get_footprints_dir, save_and_render


def test_get_builder_invalid_footprint(tmpdir) -> None:
    pcb_path = f"{tmpdir}/test.kicad_pcb"
    invalid_footprint = "SW_Cherry_MX_PCB_1.00u"
    with pytest.raises(
        ValueError, match=f"Unexpected footprint value: `{invalid_footprint}`"
    ):
        BoardBuilder(
            pcb_path,
            switch_footprint=invalid_footprint,
            diode_footprint=invalid_footprint,
        )


@pytest.fixture
def builder(tmpdir, request) -> BoardBuilder:
    pcb_path = f"{tmpdir}/test.kicad_pcb"
    switch_footprint = str(get_footprints_dir(request)) + ":SW_Cherry_MX_PCB_1.00u"
    diode_footprint = str(get_footprints_dir(request)) + ":D_SOD-323"
    return BoardBuilder(
        pcb_path, switch_footprint=switch_footprint, diode_footprint=diode_footprint
    )


@pytest.mark.parametrize("input_callback", [lambda x: x, get_keyboard_from_file])
def test_create_board(tmpdir, request, builder, input_callback) -> None:
    test_dir = request.fspath.dirname
    layout = Path(test_dir) / "data/via-layouts/crkbd.json"

    layout = input_callback(layout)
    board = builder.create_board(layout)

    # board builder only adds footprints and nets,
    # it does not do any placement or routing
    for f in board.GetFootprints():
        assert f.GetPosition() == pcbnew.VECTOR2I(0, 0)
    assert len(board.GetTracks()) == 0

    switch_annotation = "SW{}"
    diode_annotation = "D{}"
    matrix = KeyMatrix(board, switch_annotation, diode_annotation)
    assert len(matrix.matrix_rows()) == 8
    assert len(matrix.matrix_columns()) == 6

    # builder supports only one diode per switch
    for reference, switch_footprint in matrix.switches_by_reference():
        diodes = matrix.diodes_by_switch_reference(reference)
        assert len(diodes) == 1
        assert len(get_common_nets(switch_footprint, diodes[0])) == 1

    save_and_render(board, tmpdir, request)


def test_create_board_not_annotated_layout(request, builder) -> None:
    test_dir = request.fspath.dirname
    layout = Path(test_dir) / "data/kle-layouts/ansi-104.json"

    with pytest.raises(
        RuntimeError,
        match=(
            "Keyboard object not convertible to matrix annotated keyboard: "
            "Matrix coordinates label missing or invalid"
        ),
    ):
        _ = builder.create_board(layout)


def test_create_board_variable_width(tmpdir, request) -> None:
    """Test board creation with variable width switch footprints.

    This test verifies that SwitchFootprintLoader automatically discovers
    and uses the appropriate width variants from the library.
    """
    pcb_path = f"{tmpdir}/test.kicad_pcb"

    # Use examples library with multiple switch widths
    test_dir = request.fspath.dirname
    examples_lib = Path(test_dir).parent / "examples" / "examples.pretty"

    if not examples_lib.exists():
        pytest.skip("Examples library not found")

    switch_footprint = f"{examples_lib}:SW_Cherry_MX_PCB_{{:.2f}}u"
    diode_footprint = str(get_footprints_dir(request)) + ":D_SOD-323"

    builder = BoardBuilder(
        pcb_path,
        switch_footprint=switch_footprint,
        diode_footprint=diode_footprint,
    )

    # Use layout with various key widths (1.0u, 1.5u, 1.75u)
    layout = Path(test_dir).parent / "examples" / "3x2-sizes" / "kle-annotated.json"

    if not layout.exists():
        pytest.skip("Example layout not found")

    board = builder.create_board(layout)

    # Verify switches were created
    switches = [
        fp for fp in board.GetFootprints() if fp.GetReference().startswith("SW")
    ]
    assert len(switches) == 6  # 3 rows × 2 columns

    # Get switch footprint names
    footprint_names = [str(fp.GetFPID().GetLibItemName()) for fp in switches]

    # Verify different width footprints were loaded
    # Layout has: 4x 1.0u (default), 1x 1.5u, 1x 1.75u
    assert footprint_names.count("SW_Cherry_MX_PCB_1.00u") == 4
    assert footprint_names.count("SW_Cherry_MX_PCB_1.50u") == 1
    assert footprint_names.count("SW_Cherry_MX_PCB_1.75u") == 1

    save_and_render(board, tmpdir, request)


def test_create_board_diode_footprint_not_found(tmpdir, request) -> None:
    test_dir = request.fspath.dirname
    layout = Path(test_dir) / "data/via-layouts/crkbd.json"

    pcb_path = f"{tmpdir}/test.kicad_pcb"
    switch_footprint = str(get_footprints_dir(request)) + ":SW_Cherry_MX_PCB_1.00u"
    diode_footprint = str(get_footprints_dir(request)) + ":D_SOD-323-NoSuchDiode"
    builder = BoardBuilder(
        pcb_path, switch_footprint=switch_footprint, diode_footprint=diode_footprint
    )
    with pytest.raises(
        RuntimeError,
        match=r"Unable to load footprint: .*tests.pretty:D_SOD-323-NoSuchDiode",
    ):
        _ = builder.create_board(layout)
