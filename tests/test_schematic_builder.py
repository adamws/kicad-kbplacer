# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pcbnew
import pytest
import sexpdata

from kbplacer.board_builder import BoardBuilder
from kbplacer.schematic_builder import can_create_schematic, create_schematic

from .conftest import (
    KICAD_VERSION,
    filter_kiacd10_errs,
    generate_netlist,
    generate_schematic_image,
    get_footprints_dir,
)

logger = logging.getLogger(__name__)


def is_symbol(x, name):
    return isinstance(x, sexpdata.Symbol) and x.value() == name


def find_child(expr, name):
    """Return first child list starting with symbol `name`"""
    for item in expr:
        if isinstance(item, list) and is_symbol(item[0], name):
            return item
    return None


def find_children(expr, name):
    """Return all child lists starting with symbol `name`"""
    return [
        item for item in expr if isinstance(item, list) and is_symbol(item[0], name)
    ]


def parse_netlist_file(netlist_path: Path):
    with open(netlist_path, "r") as f:
        netlist_sexp = sexpdata.load(f)
        nets = find_child(netlist_sexp, "nets")
        nets_parsed = []
        for net in find_children(nets, "net"):
            netinfo = {
                "code": None,
                "name": None,
                "class": None,
                "nodes": [],
            }

            for item in net[1:]:
                if is_symbol(item[0], "code"):
                    netinfo["code"] = item[1]
                elif is_symbol(item[0], "name"):
                    netinfo["name"] = item[1]
                elif is_symbol(item[0], "class"):
                    netinfo["class"] = item[1]
                elif is_symbol(item[0], "node"):
                    node = {}
                    for field in item[1:]:
                        node[field[0].value()] = field[1]
                    netinfo["nodes"].append(node)

            nets_parsed.append(netinfo)
        return nets_parsed


def parse_netinfo_item(netinfo: pcbnew.NETINFO_ITEM):
    netinfo_parsed = {
        "code": netinfo.GetNetCode(),
        "name": netinfo.GetNetname(),
        "class": netinfo.GetNetClassName(),
    }
    return netinfo_parsed


class TestSchematicBuilderCli:
    def _run_subprocess(
        self,
        package_path,
        package_name,
        flags: list[str] = [],
        args: dict[str, str] = {},
    ) -> subprocess.Popen:
        kbplacer_args = ["python3", "-m", f"{package_name}", "--create-sch-file"]
        for v in flags:
            kbplacer_args.append(v)
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

    def example_isolation(self, request, tmpdir, example_data) -> str:
        example, layout_file = example_data[0], example_data[1]
        test_dir = request.fspath.dirname
        source_dir = f"{test_dir}/../examples/{example}"
        shutil.copy(f"{source_dir}/{layout_file}", tmpdir)
        return f"{tmpdir}/{layout_file}"

    @pytest.mark.parametrize(
        "example_data",
        [
            ("2x2", "kle-annotated.json"),
            ("3x2-sizes", "kle-annotated.json"),
            ("2x2-with-alternative-layout", "via.json"),
        ],
    )
    def test_schematic_build(
        self, request, tmpdir, package_path, package_name, example_data
    ) -> None:
        layout_file = self.example_isolation(request, tmpdir, example_data)

        pcb_file = Path(layout_file).with_suffix(".kicad_pcb")
        schematic_file = Path(layout_file).with_suffix(".kicad_sch")

        switch_footprint = str(get_footprints_dir(request)) + ":SW_Cherry_MX_PCB_1.00u"
        diode_footprint = str(get_footprints_dir(request)) + ":D_SOD-323"
        stabilizer_footprint = (
            str(get_footprints_dir(request)) + ":Stabilizer_Cherry_MX_{:.2f}u"
        )

        p = self._run_subprocess(
            package_path,
            package_name,
            args={
                "--layout": layout_file,
                "--pcb-file": str(pcb_file),
                "--sch-file": str(schematic_file),
                "--switch-footprint": switch_footprint,
                "--diode-footprint": diode_footprint,
                "--stabilizer-footprint": stabilizer_footprint,
            },
            flags=["--create-pcb-file"],
        )
        outs, errs = p.communicate()

        logger.info(f"Process stdout: {outs}")
        logger.info(f"Process stderr: {errs}")

        if KICAD_VERSION < (9, 0, 0):
            assert "Requires KiCad 9.0 or higher" in errs
            assert p.returncode == 1
            return

        if sys.platform != "darwin":
            # getting:
            # 'assert ""traits"" failed in Get(): create wxApp before calling this'
            # only on macos (otherwise it works just fine)
            assert filter_kiacd10_errs(errs) == ""
        assert p.returncode == 0

        generate_schematic_image(tmpdir, schematic_file)
        netlist = generate_netlist(tmpdir, schematic_file)
        assert netlist.exists()
        nets_parsed = parse_netlist_file(netlist)
        for n in nets_parsed:
            logger.debug(n)
            assert "unconnected" not in n["name"]

        # Test compatibility with created board.
        # The kicad-cli currently does not support converting netlist to kicad_pcb file.
        # We generate schematic and pcb files independently
        # and hope that they would match...

        board = pcbnew.LoadBoard(str(pcb_file))
        board_nets = board.GetNetsByNetcode()
        board_nets_parsed = []
        for netcode, netinfo in board_nets.items():
            netinfo_parsed = parse_netinfo_item(netinfo)
            logger.debug(f"{netcode=} {netinfo_parsed=}")
            board_nets_parsed.append(netinfo_parsed)

        # Compare nets from schematic and board.
        # Filter out netcode=0 and ignore 'nodes' field.
        # KiCad 10 changed .kicad_pcb to store nets by name only (no numeric
        # codes in the file), so codes are dynamically assigned on load and
        # differ between board and schematic. For KiCad < 10, codes are stored
        # in the file and should match.
        def _normalize(nets):
            if KICAD_VERSION >= (10, 0, 0):
                return [(n["name"], n["class"]) for n in nets if int(n["code"]) != 0]
            return [
                (int(n["code"]), n["name"], n["class"])
                for n in nets
                if int(n["code"]) != 0
            ]

        nets_for_comparison = _normalize(nets_parsed)
        board_nets_for_comparison = _normalize(board_nets_parsed)

        # Convert to sets for order-independent comparison
        nets_set = set(nets_for_comparison)
        board_nets_set = set(board_nets_for_comparison)

        assert len(nets_set) == len(board_nets_set), (
            f"Different number of nets: schematic has {len(nets_set)}, "
            f"board has {len(board_nets_set)}"
        )
        assert nets_set == board_nets_set, (
            f"Nets mismatch:\n"
            f"Only in schematic: {nets_set - board_nets_set}\n"
            f"Only in board: {board_nets_set - nets_set}"
        )

    @pytest.mark.skipif(
        KICAD_VERSION < (9, 0, 0), reason="Requires KiCad 9.0 or higher"
    )
    def test_defined_footprints_variable_width(
        self, request, tmpdir, package_path, package_name
    ) -> None:
        layout_file = self.example_isolation(
            request,
            tmpdir,
            ("3x2-sizes", "kle-annotated.json"),
        )
        schematic_file = Path(layout_file).with_suffix(".kicad_sch")

        switch_footprint = str(get_footprints_dir(request)) + ":switch_{:.2f}u"
        diode_footprint = str(get_footprints_dir(request)) + ":D_SOD-323"

        p = self._run_subprocess(
            package_path,
            package_name,
            args={
                "--layout": layout_file,
                "--sch-file": str(schematic_file),
                # schematic builder support footprints with variable width
                "--switch-footprint": switch_footprint,
                "--diode-footprint": diode_footprint,
            },
        )
        _, errs = p.communicate()

        if sys.platform != "darwin":
            assert filter_kiacd10_errs(errs) == ""
        assert p.returncode == 0

        generate_schematic_image(tmpdir, schematic_file)
        netlist = generate_netlist(tmpdir, schematic_file)
        assert netlist.exists()
        with open(netlist, "r") as f:
            netlist_str = f.read()
            assert netlist_str.count("switch_1.00u") == 8
            assert netlist_str.count("switch_1.50u") == 2
            assert netlist_str.count("switch_1.75u") == 2
            assert netlist_str.count("D_SOD-323") == 12

    def test_warn_if_output_already_exist(
        self, request, tmpdir, package_path, package_name
    ) -> None:
        layout_file = self.example_isolation(
            request, tmpdir, ("2x2", "kle-annotated.json")
        )
        schematic_file = Path(layout_file).with_suffix(".kicad_sch")

        with open(schematic_file, "w") as f:
            f.write("dummy")

        p = self._run_subprocess(
            package_path,
            package_name,
            args={
                "--layout": layout_file,
                "--sch-file": str(schematic_file),
            },
        )
        _, errs = p.communicate()

        assert f"File {schematic_file} already exist, aborting" in errs
        assert p.returncode == 1

    @pytest.mark.skipif(
        KICAD_VERSION < (9, 0, 0), reason="Requires KiCad 9.0 or higher"
    )
    def test_invalid_stabilizer_footprint(
        self, request, tmpdir, package_path, package_name
    ) -> None:
        layout_file = self.example_isolation(
            request, tmpdir, ("2x2", "kle-annotated.json")
        )
        schematic_file = Path(layout_file).with_suffix(".kicad_sch")

        p = self._run_subprocess(
            package_path,
            package_name,
            args={
                "--layout": layout_file,
                "--sch-file": str(schematic_file),
                # valid footprint id but missing the size format placeholder
                "--stabilizer-footprint": "SomeLib.pretty:Stabilizer_Cherry_MX_2u",
            },
        )
        _, errs = p.communicate()

        assert (
            "Stabilizer footprint, if defined, must use size-templated definition"
            in errs
        )
        assert p.returncode == 1

    @pytest.mark.skipif(
        KICAD_VERSION < (9, 0, 0), reason="Requires KiCad 9.0 or higher"
    )
    def test_wrong_annotation(
        self, request, tmpdir, package_path, package_name
    ) -> None:
        layout_file = self.example_isolation(request, tmpdir, ("2x2", "kle.json"))
        schematic_file = Path(layout_file).with_suffix(".kicad_sch")

        p = self._run_subprocess(
            package_path,
            package_name,
            args={
                "--layout": layout_file,
                "--sch-file": str(schematic_file),
            },
        )
        _, errs = p.communicate()

        assert "Matrix coordinates label missing or invalid" in errs
        assert p.returncode == 1


class TestEncoderBoardSchematic:
    # Layout: 2x2 matrix with rotary encoder at position (0,1)
    # Row 0: key "0,0", encoder (sm='rot_ec11'), key "0,1"
    # Row 1: key (sm=''), key "1,0", key "1,1"
    # Encoder inherits sm from the dict preceding it in the KLE raw row
    ENCODER_LAYOUT_1 = [
        ["0,0", {"sm": "rot_ec11"}, "0,1"],
        [{"sm": ""}, "1,0", "1,1"],
    ]
    # 2 encoders, both as alternative choice for a regular switch,
    # with a space key forcing use of stabilizer to test if encoder
    # symbols are placed correctly
    ENCODER_LAYOUT_2 = [
        [
            "0,0\n\n\n0,0",
            "0,1\n\n\n1,0",
            {"x": 0.5, "sm": "rot_ec11"},
            "0,0\n\n\n0,1\n\n\n\n\n\ne0",
            "0,1\n\n\n1,1\n\n\n\n\n\ne1",
        ],
        [{"sm": "", "w": 2}, "1,0"],
    ]

    @pytest.mark.skipif(
        KICAD_VERSION < (10, 0, 0), reason="Requires KiCad 10.0 or higher"
    )
    @pytest.mark.parametrize(
        "layout,expected_encoder_count",
        [
            (ENCODER_LAYOUT_1, 1),
            (ENCODER_LAYOUT_2, 2),
        ],
    )
    def test_encoder_board(
        self, request, tmpdir, layout, expected_encoder_count
    ) -> None:
        if not can_create_schematic():
            pytest.skip("Requires optional schematic dependencies")

        layout_file = Path(tmpdir) / "layout.json"
        with open(layout_file, "w") as f:
            json.dump(layout, f)

        pcb_file = Path(tmpdir) / "test.kicad_pcb"
        schematic_file = Path(tmpdir) / "test.kicad_sch"

        fp_dir = str(get_footprints_dir(request))
        switch_footprint = fp_dir + ":SW_Cherry_MX_PCB_1.00u"
        diode_footprint = fp_dir + ":D_SOD-323"
        encoder_footprint = (
            fp_dir
            + ":RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm_CircularMountingHoles"
        )

        # Create schematic
        create_schematic(
            layout_file,
            schematic_file,
            switch_footprint=switch_footprint,
            diode_footprint=diode_footprint,
        )

        # Create board
        builder = BoardBuilder(
            pcb_file,
            switch_footprint=switch_footprint,
            diode_footprint=diode_footprint,
            encoder_footprint=encoder_footprint,
        )
        board = builder.create_board(layout_file)
        board.Save(str(pcb_file))

        # Verify encoder footprints are present in the board
        encoder_fps = [
            f for f in board.GetFootprints() if f.GetValue() == "RotaryEncoder_Switch"
        ]
        assert len(encoder_fps) == expected_encoder_count, (
            f"Expected {expected_encoder_count} encoder footprints, "
            f"got {len(encoder_fps)}"
        )

        # Generate netlist from schematic and compare with board nets
        generate_schematic_image(tmpdir, schematic_file)
        netlist = generate_netlist(tmpdir, schematic_file)
        assert netlist.exists()
        nets_parsed = parse_netlist_file(netlist)
        for n in nets_parsed:
            logger.debug(n)

        board_nets = board.GetNetsByNetcode()
        board_nets_parsed = []
        for netcode, netinfo in board_nets.items():
            netinfo_parsed = parse_netinfo_item(netinfo)
            logger.debug(f"{netcode=} {netinfo_parsed=}")
            board_nets_parsed.append(netinfo_parsed)

        # Compare nets from schematic and board.
        # Filter out unconnected nets (encoder A/B/C output pins are
        # not part of the matrix and are left unconnected in the schematic).
        def _normalize(nets):
            if KICAD_VERSION >= (10, 0, 0):
                # KiCad 10 prefixes locally-labeled schematic nets with '/'
                # (hierarchical path notation); board nets have no such prefix.
                return [
                    (n["name"].lstrip("/"), n["class"])
                    for n in nets
                    if int(n["code"]) != 0 and "unconnected" not in n["name"]
                ]
            return [
                (int(n["code"]), n["name"], n["class"])
                for n in nets
                if int(n["code"]) != 0 and "unconnected" not in n["name"]
            ]

        nets_set = set(_normalize(nets_parsed))
        board_nets_set = set(_normalize(board_nets_parsed))

        assert len(nets_set) == len(board_nets_set), (
            f"Different number of nets: schematic has {len(nets_set)}, "
            f"board has {len(board_nets_set)}"
        )
        assert nets_set == board_nets_set, (
            f"Nets mismatch:\n"
            f"Only in schematic: {nets_set - board_nets_set}\n"
            f"Only in board: {board_nets_set - nets_set}"
        )

    @pytest.mark.skipif(
        KICAD_VERSION < (9, 0, 0), reason="Requires KiCad 9.0 or higher"
    )
    def test_single_encoder_key(self, tmpdir) -> None:
        # Regression test: a layout whose only key is a rotary encoder has no
        # regular matrix keys, so no row/column labels are created and
        # `labels_positions` ends up empty. Stabilizer/encoder placement used
        # to call min() on that empty mapping and crash with
        # `ValueError: min() iterable argument is empty`. Placement must now
        # succeed and still emit the encoder symbol.
        if not can_create_schematic():
            pytest.skip("Requires optional schematic dependencies")

        # `sm` is sticky in KLE and applies to the following key, making "0,0"
        # a rotary encoder.
        layout = [[{"sm": "rot_ec11"}, "0,0"]]
        layout_file = Path(tmpdir) / "layout.json"
        with open(layout_file, "w") as f:
            json.dump(layout, f)

        schematic_file = Path(tmpdir) / "test.kicad_sch"

        # Must not raise.
        create_schematic(layout_file, schematic_file)
        assert schematic_file.exists()

        # Generate netlist from schematic
        generate_schematic_image(tmpdir, schematic_file)

        with open(schematic_file, "r") as f:
            schematic_sexp = sexpdata.load(f)
        encoder_symbols = [
            s
            for s in find_children(schematic_sexp, "symbol")
            if (lib_id := find_child(s, "lib_id")) is not None
            and lib_id[1] == "Device:RotaryEncoder_Switch"
        ]
        assert len(encoder_symbols) == 1


class TestSingleKeySchematic:
    @pytest.mark.skipif(
        KICAD_VERSION < (9, 0, 0), reason="Requires KiCad 9.0 or higher"
    )
    def test_single_regular_key(self, tmpdir) -> None:
        # A layout with a single regular (non-encoder) switch is supported: the
        # one key emits its own row/column labels, so `labels_positions` is not
        # empty and placement has positions to work with. Verify the schematic
        # is created with exactly one switch and one diode.
        if not can_create_schematic():
            pytest.skip("Requires optional schematic dependencies")

        layout = [["0,0"]]
        layout_file = Path(tmpdir) / "layout.json"
        with open(layout_file, "w") as f:
            json.dump(layout, f)

        schematic_file = Path(tmpdir) / "test.kicad_sch"

        # Must not raise.
        create_schematic(layout_file, schematic_file)
        assert schematic_file.exists()

        # Smoke-check that the produced schematic is renderable.
        generate_schematic_image(tmpdir, schematic_file)

        with open(schematic_file, "r") as f:
            schematic_sexp = sexpdata.load(f)

        def _instances(lib_id_value):
            return [
                s
                for s in find_children(schematic_sexp, "symbol")
                if (lib_id := find_child(s, "lib_id")) is not None
                and lib_id[1] == lib_id_value
            ]

        assert len(_instances("Switch:SW_Push_45deg")) == 1
        assert len(_instances("Device:D_Small")) == 1
        # A single regular key needs neither encoders nor stabilizers.
        assert len(_instances("Device:RotaryEncoder_Switch")) == 0
        assert len(_instances("Mechanical:SW_stab")) == 0
