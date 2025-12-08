# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import KICAD_VERSION, generate_netlist, generate_schematic_image

logger = logging.getLogger(__name__)


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
