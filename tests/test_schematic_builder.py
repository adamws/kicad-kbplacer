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

logger = logging.getLogger(__name__)


class TestSchematicBuilderCli:
    def _run_subprocess(
        self,
        package_path,
        package_name,
        args: dict[str, str] = {},
    ) -> subprocess.Popen:
        kbplacer_args = [
            "python3",
            "-m",
            f"{package_name}.schematic_builder",
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
    def example_isolation(self, request, tmpdir, example) -> str:
        test_dir = request.fspath.dirname
        source_dir = f"{test_dir}/../examples/{example}"
        shutil.copy(f"{source_dir}/kle-annotated.json", tmpdir)
        return f"{tmpdir}/kle-annotated.json"

    @pytest.mark.parametrize(
        "example", ["2x2", "3x2-sizes", "2x3-rotations", "1x4-rotations-90-step"]
    )
    def test_schematic_build(
        self, package_path, package_name, example_isolation
    ) -> None:
        layout_file = example_isolation
        schematic_file = Path(layout_file).with_suffix(".kicad_sch")

        p = self._run_subprocess(
            package_path,
            package_name,
            {
                "--in": layout_file,
                "--out": str(schematic_file),
            },
        )
        outs, errs = p.communicate()

        logger.info(f"Process stdout: {outs}")
        logger.info(f"Process stderr: {errs}")

        assert p.returncode == 0

        # TODO:
        # assert that 1) schematic can be opened
        # 2) netlist can be generated
