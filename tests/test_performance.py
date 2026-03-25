# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import dataclasses
import itertools
import json
import logging
from pathlib import Path
from typing import List

import pytest

from kbplacer.defaults import DEFAULT_DIODE_POSITION
from kbplacer.element_position import ElementInfo, PositionOption
from kbplacer.kbplacer_plugin import PluginSettings, run_board

from .conftest import get_footprints_dir, prepare_project_file

logger = logging.getLogger(__name__)

# Standard 65% ANSI layout (61 keys) with row,column matrix annotations.
LAYOUT_65: List = [
    # fmt: off
    [
        {"c": "#777777"}, "0,0",
        {"c": "#cccccc"}, "0,1", "0,2", "0,3", "0,4", "0,5",
        "0,6", "0,7", "0,8", "0,9", "0,10", "0,11", "0,12",
        {"c": "#aaaaaa", "w": 2}, "0,13",
    ],
    [
        {"w": 1.5}, "1,0",
        {"c": "#cccccc"}, "1,1", "1,2", "1,3", "1,4", "1,5",
        "1,6", "1,7", "1,8", "1,9", "1,10", "1,11", "1,12",
        {"c": "#aaaaaa", "w": 1.5}, "1,13",
    ],
    [
        {"w": 1.75}, "2,0",
        {"c": "#cccccc"}, "2,1", "2,2", "2,3", "2,4", "2,5",
        "2,6", "2,7", "2,8", "2,9", "2,10", "2,11",
        {"c": "#777777", "w": 2.25}, "2,13",
    ],
    [
        {"c": "#aaaaaa", "w": 2.25}, "3,0",
        {"c": "#cccccc"}, "3,1", "3,2", "3,3", "3,4", "3,5",
        "3,6", "3,7", "3,8", "3,9", "3,10",
        {"c": "#aaaaaa", "w": 2.75}, "3,13",
    ],
    [
        {"c": "#aaaaaa", "w": 1.25}, "4,0",
        {"w": 1.25}, "4,1",
        {"w": 1.25}, "4,2",
        {"c": "#777777", "w": 6.25}, "5,5",
        {"c": "#aaaaaa", "w": 1.25}, "5,9",
        {"w": 1.25}, "5,10",
        {"w": 1.25}, "5,12",
        {"w": 1.25}, "5,13",
    ],
    # fmt: on
]

# Number of benchmark rounds (each round creates a fresh board).
BENCHMARK_ROUNDS = 50


@pytest.mark.performance
def test_performance_65percent_all_features(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    benchmark,
) -> None:
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(json.dumps(LAYOUT_65))
    footprints_dir = get_footprints_dir(request)

    settings_template = PluginSettings(
        pcb_file_path="",  # filled per round in setup()
        layout_path=str(layout_path),
        key_info=ElementInfo("SW{}", PositionOption.DEFAULT, None, ""),
        key_distance=None,
        diode_info=ElementInfo(
            "D{}", PositionOption.CUSTOM, DEFAULT_DIODE_POSITION, ""
        ),
        route_switches_with_diodes=True,
        optimize_diodes_orientation=True,
        route_rows_and_columns=True,
        additional_elements=[],
        generate_outline=True,
        outline_delta=1.0,
        template_path="",
        create_pcb_file=True,
        create_sch_file=False,
        sch_file_path="",
        switch_footprint=f"{footprints_dir}:SW_Cherry_MX_PCB_1.00u",
        diode_footprint=f"{footprints_dir}:D_SOD-323F",
        stabilizer_footprint="",
        add_stabilizers=False,
    )

    run_counter = itertools.count()

    def setup():
        """Called before each timed invocation; not included in the measurement."""
        i = next(run_counter)
        pcb_path = tmp_path / f"keyboard_{i}.kicad_pcb"
        # .kicad_pro must exist so NewBoard() picks up netclass settings.
        prepare_project_file(request, pcb_path)
        settings = dataclasses.replace(settings_template, pcb_file_path=str(pcb_path))
        return (settings,), {}

    def run_and_save(settings: PluginSettings) -> None:
        board = run_board(settings)
        board.Save(settings.pcb_file_path)

    benchmark.pedantic(
        run_and_save,
        setup=setup,
        rounds=BENCHMARK_ROUNDS,
        iterations=1,
        warmup_rounds=0,
    )
