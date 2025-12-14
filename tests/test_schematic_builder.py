# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

import pcbnew
import pytest
import sexpdata

from kbplacer.board_builder import BoardBuilder

from .conftest import (
    KICAD_VERSION,
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
        kbplacer_args = [
            "python3",
            "-m",
            f"{package_name}.schematic_builder",
        ]
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
        schematic_file = Path(layout_file).with_suffix(".kicad_sch")

        p = self._run_subprocess(
            package_path,
            package_name,
            flags=["--force"],
            args={
                "--in": layout_file,
                "--out": str(schematic_file),
            },
        )
        outs, errs = p.communicate()

        logger.info(f"Process stdout: {outs}")
        logger.info(f"Process stderr: {errs}")

        if KICAD_VERSION < (9, 0, 0):
            assert "Requires KiCad 9.0 or higher" in errs
            assert p.returncode == 1
        else:
            assert errs == ""
            assert p.returncode == 0

            generate_schematic_image(tmpdir, schematic_file)
            netlist = generate_netlist(tmpdir, schematic_file)
            assert netlist.exists()
            nets_parsed = parse_netlist_file(netlist)
            for n in nets_parsed:
                logger.debug(n)
                assert "unconnected" not in n["name"]
            # Test compatibility with board_builder.
            # The kicad-cli currently does not support converting netlist to kicad_pcb file.
            # We generate schematic and pcb files independently
            # and hope that they would match...
            board_path = f"{tmpdir}/test.kicad_pcb"
            builder = BoardBuilder(
                board_path,
                switch_footprint=str(get_footprints_dir(request))
                + ":SW_Cherry_MX_PCB_1.00u",
                diode_footprint=str(get_footprints_dir(request)) + ":D_SOD-323",
            )
            board = builder.create_board(layout_file)

            board_nets = board.GetNetsByNetcode()
            board_nets_parsed = []
            for netcode, netinfo in board_nets.items():
                netinfo_parsed = parse_netinfo_item(netinfo)
                logger.debug(f"{netcode=} {netinfo_parsed=}")
                board_nets_parsed.append(netinfo_parsed)

            # Compare nets from schematic and board
            # Filter out netcode=0 and ignore 'nodes' field
            def _normalize(nets):
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
    def test_defined_footprints(
        self, request, tmpdir, package_path, package_name
    ) -> None:
        layout_file = self.example_isolation(
            request,
            tmpdir,
            ("3x2-sizes", "kle-annotated.json"),
        )
        schematic_file = Path(layout_file).with_suffix(".kicad_sch")

        p = self._run_subprocess(
            package_path,
            package_name,
            args={
                "--in": layout_file,
                "--out": str(schematic_file),
                # schematic builder does not check if footprints actually exist,
                # it assigns any provided value
                "-swf": "Switches:dummy_switch_footprint",
                "-df": "Diodes:dummy_diode_footprint",
            },
        )
        _, errs = p.communicate()

        assert errs == ""
        assert p.returncode == 0

        generate_schematic_image(tmpdir, schematic_file)
        netlist = generate_netlist(tmpdir, schematic_file)
        assert netlist.exists()
        with open(netlist, "r") as f:
            netlist_str = f.read()
            assert netlist_str.count("dummy_switch_footprint") == 12
            assert netlist_str.count("dummy_diode_footprint") == 12

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

        p = self._run_subprocess(
            package_path,
            package_name,
            args={
                "--in": layout_file,
                "--out": str(schematic_file),
                # schematic builder support footprints with variable width
                "-swf": "Switches:dummy_switch_footprint_{:.2f}u",
                "-df": "Diodes:dummy_diode_footprint",
            },
        )
        _, errs = p.communicate()

        assert errs == ""
        assert p.returncode == 0

        generate_schematic_image(tmpdir, schematic_file)
        netlist = generate_netlist(tmpdir, schematic_file)
        assert netlist.exists()
        with open(netlist, "r") as f:
            netlist_str = f.read()
            assert netlist_str.count("dummy_switch_footprint_1.00u") == 8
            assert netlist_str.count("dummy_switch_footprint_1.50u") == 2
            assert netlist_str.count("dummy_switch_footprint_1.75u") == 2
            assert netlist_str.count("dummy_diode_footprint") == 12

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
                "--in": layout_file,
                "--out": str(schematic_file),
            },
        )
        _, errs = p.communicate()

        assert f"Output file '{schematic_file}' already exists, exiting..." in errs
        assert p.returncode == 1

    def test_wrong_annotation(
        self, request, tmpdir, package_path, package_name
    ) -> None:
        layout_file = self.example_isolation(request, tmpdir, ("2x2", "kle.json"))
        schematic_file = Path(layout_file).with_suffix(".kicad_sch")

        p = self._run_subprocess(
            package_path,
            package_name,
            args={
                "--in": layout_file,
                "--out": str(schematic_file),
            },
        )
        _, errs = p.communicate()

        assert "Matrix coordinates label missing or invalid" in errs
        assert p.returncode == 1
