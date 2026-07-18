# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import itertools
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pcbnew
import pytest

from kbplacer.board_builder import BoardBuilder
from kbplacer.board_modifier import get_common_nets
from kbplacer.key_placer import KeyMatrix
from kbplacer.kle_serial import (
    MatrixAnnotatedKeyboard,
    get_keyboard_from_file,
    parse_kle,
)

from .conftest import (
    KICAD_VERSION,
    filter_kiacd10_errs,
    get_footprints_dir,
    save_and_render,
)


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

    switch_footprint = f"{examples_lib}:SW_Cherry_MX_PCB_{{:.2f}}u"
    diode_footprint = str(get_footprints_dir(request)) + ":D_SOD-323"

    builder = BoardBuilder(
        pcb_path,
        switch_footprint=switch_footprint,
        diode_footprint=diode_footprint,
    )

    # Use layout with various key widths (1.0u, 1.5u, 1.75u)
    layout = Path(test_dir).parent / "examples" / "3x2-sizes" / "kle-annotated.json"
    assert layout.exists()

    board = builder.create_board(layout)

    # Verify switches were created
    switches = [
        fp for fp in board.GetFootprints() if fp.GetReference().startswith("SW")
    ]
    assert len(switches) == 6  # 3 rows x 2 columns

    # Get switch footprint names
    footprint_names = [str(fp.GetFPID().GetLibItemName()) for fp in switches]

    # Verify different width footprints were loaded
    # Layout has: 4x 1.0u (default), 1x 1.5u, 1x 1.75u
    assert footprint_names.count("SW_Cherry_MX_PCB_1.00u") == 4
    assert footprint_names.count("SW_Cherry_MX_PCB_1.50u") == 1
    assert footprint_names.count("SW_Cherry_MX_PCB_1.75u") == 1

    save_and_render(board, tmpdir, request)


def test_create_board_alternative_layout_loads_correct_footprint(
    tmpdir, request
) -> None:
    """Test that alternative layout keys load their own footprint, not a duplicate.

    Position (1,0) has a 1.0u default and a 2.0u alternative. The alternative
    switch must get the 2.0u footprint loaded and inherit net assignments from
    the default switch.
    """
    pcb_path = f"{tmpdir}/test.kicad_pcb"

    test_dir = request.fspath.dirname
    examples_lib = Path(test_dir).parent / "examples" / "examples.pretty"

    switch_footprint = f"{examples_lib}:SW_Cherry_MX_PCB_{{:.2f}}u"
    diode_footprint = str(get_footprints_dir(request)) + ":D_SOD-323"

    builder = BoardBuilder(
        pcb_path, switch_footprint=switch_footprint, diode_footprint=diode_footprint
    )

    layout = (
        Path(test_dir).parent / "examples" / "2x2-with-alternative-layout" / "via.json"
    )
    assert layout.exists()

    board = builder.create_board(layout)

    switches = {
        fp.GetReference(): fp
        for fp in board.GetFootprints()
        if fp.GetReference().startswith("SW")
    }

    # SW3 is the default 1.0u key at (1,0); SW3a is the 2.0u alternative
    assert "SW3" in switches
    assert "SW3a" in switches
    assert str(switches["SW3"].GetFPID().GetLibItemName()) == "SW_Cherry_MX_PCB_1.00u"
    assert str(switches["SW3a"].GetFPID().GetLibItemName()) == "SW_Cherry_MX_PCB_2.00u"

    # Alternative switch must share the same nets as the default
    for pad_number in ("1", "2"):
        default_net = switches["SW3"].FindPadByNumber(pad_number).GetNet().GetNetname()
        alt_net = switches["SW3a"].FindPadByNumber(pad_number).GetNet().GetNetname()
        assert (
            default_net == alt_net
        ), f"Pad {pad_number}: default net '{default_net}' != alternative net '{alt_net}'"

    save_and_render(board, tmpdir, request)


@pytest.mark.skipif(
    KICAD_VERSION < (10, 0, 0),
    reason="Encoder footprint not recognized by KiCad older than 10.0",
)
def test_create_board_encoder_default_switch_alternative(tmpdir, request) -> None:
    """Encoder as the default key with a plain switch alternative at the same
    position.

    Regression test: previously the alternative plain switch (``SW1a``) inherited
    its nets from the default footprint by pad numbers ``1``/``2``. When the
    default is an encoder its matrix pads are named ``S1``/``S2``, so the lookup
    returned nothing and the alternative switch was left with unconnected pads.
    That in turn made ``KeyMatrix`` reject the whole board as not associable with
    matrix positions. The alternative switch must inherit the encoder's matrix
    nets so the matrix stays valid.
    """
    pcb_path = f"{tmpdir}/test.kicad_pcb"

    fp_dir = str(get_footprints_dir(request))
    switch_footprint = f"{fp_dir}:SW_Cherry_MX_PCB_1.00u"
    diode_footprint = f"{fp_dir}:D_SOD-323"
    encoder_footprint = (
        f"{fp_dir}:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm_CircularMountingHoles"
    )

    builder = BoardBuilder(
        pcb_path,
        switch_footprint=switch_footprint,
        diode_footprint=diode_footprint,
        encoder_footprint=encoder_footprint,
    )

    # default at (0,0) is the encoder (choice 0), alternative is a plain switch
    keyboard = parse_kle(
        [
            [
                {"sm": "rot_ec11"},
                "0,0\n\n\n1,0\n\n\n\n\n\ne0",
                {"sm": ""},
                "0,0\n\n\n1,1",
            ],
            ["0,1", "1,1"],
        ]
    )
    keyboard = MatrixAnnotatedKeyboard(meta=keyboard.meta, keys=keyboard.keys)

    board = builder.create_board(keyboard)

    switches = {
        fp.GetReference(): fp
        for fp in board.GetFootprints()
        if fp.GetReference().startswith("SW")
    }
    # SW1 is the default encoder at (0,0); SW1a is the plain switch alternative
    assert "SW1" in switches
    assert "SW1a" in switches

    # The alternative switch's matrix pads ('1'/'2') must inherit the encoder's
    # matrix nets ('S1'/'S2') and none of them may be left unconnected.
    for encoder_pad, switch_pad in (("S1", "1"), ("S2", "2")):
        encoder_net = switches["SW1"].FindPadByNumber(encoder_pad).GetNet().GetNetname()
        alt_net = switches["SW1a"].FindPadByNumber(switch_pad).GetNet().GetNetname()
        assert alt_net != "", f"SW1a pad {switch_pad} left unconnected"
        assert (
            encoder_net == alt_net
        ), f"pad {switch_pad}: encoder net '{encoder_net}' != alternative net '{alt_net}'"

    # With both footprints correctly netted the matrix must be associable.
    matrix = KeyMatrix(board, "SW{}", "D{}")
    assert matrix.invalid_switches() == {}
    assert matrix.is_matrix_ok()

    save_and_render(board, tmpdir, request)


def test_create_board_leading_zero_matrix_label(tmpdir, request, builder) -> None:
    """Leading-zero matrix labels must not create phantom nets.

    A label like ``0,00`` denotes the same matrix column as ``0,0``. The board
    builder must normalize digit-only coordinates through int() so the switch
    lands on ``COL0`` (the canonical net used by the int-based placement lookup)
    instead of a separate, unreachable ``COL00`` net.
    """
    keyboard = parse_kle([["0,00"], ["1,0"]])
    keyboard = MatrixAnnotatedKeyboard(meta=keyboard.meta, keys=keyboard.keys)

    board = builder.create_board(keyboard)

    switches = {
        fp.GetReference(): fp
        for fp in board.GetFootprints()
        if fp.GetReference().startswith("SW")
    }
    assert set(switches) == {"SW1", "SW2"}

    # Both keys are in column 0; the leading-zero variant must collapse onto COL0
    sw1_col_net = switches["SW1"].FindPadByNumber("1").GetNet().GetNetname()
    sw2_col_net = switches["SW2"].FindPadByNumber("1").GetNet().GetNetname()
    assert sw1_col_net == "COL0"
    assert sw2_col_net == "COL0"

    # No phantom COL00 net is created
    net_names = {str(n.GetNetname()) for n in board.GetNetInfo().NetsByName().values()}
    assert "COL0" in net_names
    assert "COL00" not in net_names

    # The placement lookup (int-based) must resolve the leading-zero position
    matrix = KeyMatrix(board, "SW{}", "D{}")
    assert "SW1" in matrix.switches_references_by_coordinates(0, 0)


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


def test_create_board_with_stabilizers(tmpdir, request) -> None:

    pcb_path = f"{tmpdir}/test.kicad_pcb"

    # Use examples library with multiple switch widths
    test_dir = request.fspath.dirname

    layout = Path(test_dir) / "data/via-layouts/wt60_d.json"
    assert layout.exists()

    footprints_dir = get_footprints_dir(request)
    switch_footprint = f"{footprints_dir}:SW_Cherry_MX_PCB_1.00u"
    diode_footprint = f"{footprints_dir}:D_SOD-323"
    stabilizer_footprint = f"{footprints_dir}:Stabilizer_Cherry_MX_{{:.2f}}u"

    builder = BoardBuilder(
        pcb_path,
        switch_footprint=switch_footprint,
        diode_footprint=diode_footprint,
        stabilizer_footprint=stabilizer_footprint,
    )
    board = builder.create_board(layout)

    # Verify switches and stabilizers were created
    switches = []
    stabilizers = []
    for fp in board.GetFootprints():
        if fp.GetReference().startswith("SW"):
            switches.append(fp)
        elif fp.GetReference().startswith("ST"):
            stabilizers.append(fp)

    assert len(switches) == 76
    assert len(stabilizers) == 7

    # Get switch footprint names
    footprint_names = [
        str(fp.GetFPID().GetLibItemName())
        for fp in itertools.chain(switches, stabilizers)
    ]

    assert footprint_names.count("SW_Cherry_MX_PCB_1.00u") == 76
    assert footprint_names.count("Stabilizer_Cherry_MX_2.00u") == 5
    assert footprint_names.count("Stabilizer_Cherry_MX_6.25u") == 1
    assert footprint_names.count("Stabilizer_Cherry_MX_7.00u") == 1

    save_and_render(board, tmpdir, request)


class TestStartIndex:
    """`create_board`'s `start_index` controls the first number used for
    both switch (SW) and diode (D) references, mirroring `--start-index`
    of the schematic builder and `key_placer` PCB placement path.
    """

    LAYOUT = [["0,0", "0,1"], ["1,0", "1,1"]]

    def _build(self, builder, **kwargs) -> pcbnew.BOARD:
        keyboard = parse_kle(self.LAYOUT)
        keyboard = MatrixAnnotatedKeyboard(meta=keyboard.meta, keys=keyboard.keys)
        return builder.create_board(keyboard, **kwargs)

    def _references(self, board, prefix):
        return sorted(
            fp.GetReference()
            for fp in board.GetFootprints()
            if fp.GetReference().startswith(prefix)
        )

    def test_default_start_index(self, builder) -> None:
        board = self._build(builder)

        assert self._references(board, "SW") == ["SW1", "SW2", "SW3", "SW4"]
        assert self._references(board, "D") == ["D1", "D2", "D3", "D4"]

    @pytest.mark.parametrize("start_index", [0, 5])
    def test_custom_start_index(self, builder, start_index) -> None:
        board = self._build(builder, start_index=start_index)

        expected = [f"SW{i}" for i in range(start_index, start_index + 4)]
        assert self._references(board, "SW") == expected
        expected = [f"D{i}" for i in range(start_index, start_index + 4)]
        assert self._references(board, "D") == expected

    def test_negative_start_index_falls_back_to_one(self, builder, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            board = self._build(builder, start_index=-5)

        assert "Invalid switch start index: -5, defaults to 1" in caplog.text
        assert self._references(board, "SW") == ["SW1", "SW2", "SW3", "SW4"]
        assert self._references(board, "D") == ["D1", "D2", "D3", "D4"]


class TestStartIndexCli:
    def _run_subprocess(
        self, package_path, package_name, args: dict[str, str]
    ) -> subprocess.Popen:
        kbplacer_args = ["python3", "-m", f"{package_name}", "--create-pcb-file"]
        for k, v in args.items():
            kbplacer_args.append(k)
            if v:
                kbplacer_args.append(v)

        p = subprocess.Popen(
            kbplacer_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            cwd=package_path,
            env=os.environ.copy(),
        )
        return p

    def test_start_index_option(
        self, request, tmpdir, package_path, package_name
    ) -> None:
        # End-to-end check of the full `--start-index` plumbing (CLI parsing ->
        # PluginSettings -> run_board -> BoardBuilder.create_board), complementing
        # the direct create_board-level checks in TestStartIndex.
        test_dir = request.fspath.dirname
        source_dir = f"{test_dir}/../examples/2x2"
        shutil.copy(f"{source_dir}/kle-annotated.json", tmpdir)
        layout_file = f"{tmpdir}/kle-annotated.json"
        pcb_file = Path(layout_file).with_suffix(".kicad_pcb")

        footprints_dir = get_footprints_dir(request)

        p = self._run_subprocess(
            package_path,
            package_name,
            args={
                "--layout": layout_file,
                "--pcb-file": str(pcb_file),
                "--switch-footprint": f"{footprints_dir}:SW_Cherry_MX_PCB_1.00u",
                "--diode-footprint": f"{footprints_dir}:D_SOD-323",
                "--start-index": "5",
            },
        )
        _, errs = p.communicate()

        if sys.platform != "darwin":
            assert filter_kiacd10_errs(errs) == ""
        assert p.returncode == 0

        board = pcbnew.LoadBoard(str(pcb_file))
        switch_refs = sorted(
            fp.GetReference()
            for fp in board.GetFootprints()
            if fp.GetReference().startswith("SW")
        )
        diode_refs = sorted(
            fp.GetReference()
            for fp in board.GetFootprints()
            if fp.GetReference().startswith("D")
        )
        assert switch_refs == ["SW5", "SW6", "SW7", "SW8"]
        assert diode_refs == ["D5", "D6", "D7", "D8"]


class TestLedChainElements:
    """`create_leds` adds one LED + one decoupling capacitor per unique
    physical key position, wired into shared VCC/GND rails and a DIN/DOUT
    daisy chain, mirroring the LED-chain schematic builder's component count,
    reference numbering (`LED{n}`/`C{n}`, paired 1:1 with `SW{n}`) and
    per-position dedup (`_unique_matrix_positions`).
    """

    LAYOUT = [["0,0", "0,1"], ["1,0", "1,1"]]

    def _led_builder(self, tmpdir, request, **kwargs) -> BoardBuilder:
        pcb_path = f"{tmpdir}/test.kicad_pcb"
        fp_dir = str(get_footprints_dir(request))
        if KICAD_VERSION >= (10, 0, 0):
            led_footprint = f"{fp_dir}:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount"
        else:
            led_footprint = f"{fp_dir}:LED_SK6812MINI_PLCC4_3.5x3.5mm_P1.75mm"
        return BoardBuilder(
            pcb_path,
            switch_footprint=f"{fp_dir}:SW_Cherry_MX_PCB_1.00u",
            diode_footprint=f"{fp_dir}:D_SOD-323",
            led_footprint=led_footprint,
            cap_footprint=f"{fp_dir}:C_0603_1608Metric",
            **kwargs,
        )

    def _build(self, builder, layout=None, **kwargs) -> pcbnew.BOARD:
        keyboard = parse_kle(self.LAYOUT if layout is None else layout)
        keyboard = MatrixAnnotatedKeyboard(meta=keyboard.meta, keys=keyboard.keys)
        return builder.create_board(keyboard, **kwargs)

    def _references(self, board, prefix):
        return sorted(
            fp.GetReference()
            for fp in board.GetFootprints()
            if fp.GetReference().startswith(prefix)
        )

    def _pad_net(self, board, ref, pad_number):
        fp = next(f for f in board.GetFootprints() if f.GetReference() == ref)
        return fp.FindPadByNumber(pad_number).GetNetname()

    def test_create_and_wire(self, tmpdir, request) -> None:
        builder = self._led_builder(tmpdir, request)
        board = self._build(builder, create_leds=True)

        save_and_render(board, tmpdir, request)

        assert self._references(board, "LED") == ["LED1", "LED2", "LED3", "LED4"]
        assert self._references(board, "C") == ["C1", "C2", "C3", "C4"]

        for ref in ("LED1", "LED2", "LED3", "LED4"):
            assert self._pad_net(board, ref, "1") == "GND"
            assert self._pad_net(board, ref, "3") == "VCC"
        for ref in ("C1", "C2", "C3", "C4"):
            assert self._pad_net(board, ref, "1") == "VCC"
            assert self._pad_net(board, ref, "2") == "GND"

        # first LED's DIN and last LED's DOUT connect to the global chain labels
        assert self._pad_net(board, "LED1", "2") == "LEDIN"
        assert self._pad_net(board, "LED4", "4") == "LEDOUT"

        # consecutive LEDs' DOUT/DIN pads share the same (internal) net
        for i in range(1, 4):
            dout_net = self._pad_net(board, f"LED{i}", "4")
            din_net = self._pad_net(board, f"LED{i + 1}", "2")
            assert dout_net == din_net

    def test_requires_led_footprint(self, tmpdir, request) -> None:
        pcb_path = f"{tmpdir}/test.kicad_pcb"
        fp_dir = str(get_footprints_dir(request))
        builder = BoardBuilder(
            pcb_path,
            switch_footprint=f"{fp_dir}:SW_Cherry_MX_PCB_1.00u",
            diode_footprint=f"{fp_dir}:D_SOD-323",
        )
        with pytest.raises(
            RuntimeError,
            match="LED footprint must be configured",
        ):
            self._build(builder, create_leds=True)

    def test_requires_cap_footprint_unless_skipped(self, tmpdir, request) -> None:
        pcb_path = f"{tmpdir}/test.kicad_pcb"
        fp_dir = str(get_footprints_dir(request))
        if KICAD_VERSION >= (10, 0, 0):
            led_footprint = f"{fp_dir}:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount"
        else:
            led_footprint = f"{fp_dir}:LED_SK6812MINI_PLCC4_3.5x3.5mm_P1.75mm"
        builder = BoardBuilder(
            pcb_path,
            switch_footprint=f"{fp_dir}:SW_Cherry_MX_PCB_1.00u",
            diode_footprint=f"{fp_dir}:D_SOD-323",
            led_footprint=led_footprint,
        )
        with pytest.raises(
            RuntimeError,
            match="Capacitor footprint must be configured",
        ):
            self._build(builder, create_leds=True)

        # With skip_led_decoupling, the missing capacitor footprint is fine.
        board = self._build(builder, create_leds=True, skip_led_decoupling=True)
        assert self._references(board, "LED") == ["LED1", "LED2", "LED3", "LED4"]
        assert not self._references(board, "C")

    def test_skip_led_decoupling(self, tmpdir, request) -> None:
        """`skip_led_decoupling` must omit the per-LED decoupling capacitor
        entirely - no `C{n}` footprint, no `VCC`/`GND` net left dangling -
        while the LED itself is still created and wired normally.
        """
        builder = self._led_builder(tmpdir, request)
        board = self._build(builder, create_leds=True, skip_led_decoupling=True)

        save_and_render(board, tmpdir, request)

        assert self._references(board, "LED") == ["LED1", "LED2", "LED3", "LED4"]
        assert not self._references(board, "C")

        for ref in ("LED1", "LED2", "LED3", "LED4"):
            assert self._pad_net(board, ref, "1") == "GND"
            assert self._pad_net(board, ref, "3") == "VCC"

        assert self._pad_net(board, "LED1", "2") == "LEDIN"
        assert self._pad_net(board, "LED4", "4") == "LEDOUT"

        for i in range(1, 4):
            dout_net = self._pad_net(board, f"LED{i}", "4")
            din_net = self._pad_net(board, f"LED{i + 1}", "2")
            assert dout_net == din_net

    def test_gate_disabled_by_default(self, tmpdir, request) -> None:
        builder = self._led_builder(tmpdir, request)
        board = self._build(builder)  # create_leds defaults to False

        assert not self._references(board, "LED")
        assert not self._references(board, "C")

    def test_no_duplicate_for_alternate_position(self, tmpdir, request) -> None:
        """Position (1,0) has a default 1.0u key and a 2.0u alternative
        (`SW3`/`SW3a`, see the alternative-layout footprint test above). Both
        share one physical spot, so it must get exactly one LED/cap -
        contrasting with stabilizers, which currently get a separate
        footprint per alternate (`ST{n}a`).
        """
        builder = self._led_builder(tmpdir, request)
        test_dir = request.fspath.dirname
        layout = (
            Path(test_dir).parent
            / "examples"
            / "2x2-with-alternative-layout"
            / "via.json"
        )
        board = builder.create_board(layout, create_leds=True)

        save_and_render(board, tmpdir, request)

        assert self._references(board, "LED") == ["LED1", "LED2", "LED3", "LED4"]
        assert self._references(board, "C") == ["C1", "C2", "C3", "C4"]

    def test_lexicographic_net_naming(self, tmpdir, request) -> None:
        """KiCad names an anonymous net after the lexicographically (string,
        not numeric) smallest "{ref}-{pin}" among the connected pins - e.g.
        "LED10-DIN" sorts before "LED9-DOUT" because '1' < '9' at the first
        differing character, even though 10 is numerically larger than 9.
        A layout with fewer than 10 unique key positions can never exercise
        this (single-digit reference numbers never invert order), so this
        uses a 10-key single-row layout.
        """
        builder = self._led_builder(tmpdir, request)
        layout = [[f"0,{i}" for i in range(10)]]
        board = self._build(builder, layout=layout, create_leds=True)

        save_and_render(board, tmpdir, request)

        assert self._pad_net(board, "LED8", "4") == "Net-(LED8-DOUT)"
        assert self._pad_net(board, "LED9", "4") == "Net-(LED10-DIN)"
