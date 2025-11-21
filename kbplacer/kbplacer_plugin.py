# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import pcbnew

from .board_builder import BoardBuilder
from .edge_generator import build_board_outline
from .element_position import ElementInfo, PositionOption
from .kbplacer_dialog import WindowState
from .key_placer import KeyPlacer
from .template_copier import copy_from_template_to_board


@dataclass
class PluginSettings:
    board_path: str
    layout_path: str
    key_info: ElementInfo
    key_distance: Tuple[float, float]
    diode_info: ElementInfo
    route_switches_with_diodes: bool
    optimize_diodes_orientation: bool
    route_rows_and_columns: bool
    additional_elements: List[ElementInfo]
    generate_outline: bool
    outline_delta: float
    template_path: str
    start_index: int
    create_from_annotated_layout: bool
    switch_footprint: str
    diode_footprint: str


def run(settings: PluginSettings) -> pcbnew.BOARD:
    if settings.create_from_annotated_layout:
        builder = BoardBuilder(
            settings.board_path,
            switch_footprint=settings.switch_footprint,
            diode_footprint=settings.diode_footprint,
        )
        board = builder.create_board(settings.layout_path)
    else:
        board = pcbnew.LoadBoard(settings.board_path)

    placer = KeyPlacer(board, settings.key_distance, settings.start_index)
    placer.run(
        settings.layout_path,
        settings.key_info,
        settings.diode_info,
        settings.route_switches_with_diodes,
        settings.route_rows_and_columns,
        additional_elements=settings.additional_elements,
        optimize_diodes_orientation=settings.optimize_diodes_orientation,
    )

    if settings.generate_outline:
        build_board_outline(
            board, settings.outline_delta, settings.key_info.annotation_format
        )

    if settings.template_path:
        copy_from_template_to_board(
            board, settings.template_path, settings.route_rows_and_columns
        )

    return board


def run_from_gui(board_path: str, state: WindowState) -> pcbnew.BOARD:
    """Same as 'run' but with additional WindowState to PluginSettings translation"""
    if not state.enable_diode_placement:
        state.diode_info.position_option = PositionOption.UNCHANGED
        state.diode_info.template_path = ""

    settings = PluginSettings(
        board_path=board_path,
        layout_path=state.layout_path,
        key_info=state.key_info,
        key_distance=state.key_distance,
        start_index=state.start_index,
        diode_info=state.diode_info,
        route_switches_with_diodes=state.route_switches_with_diodes,
        optimize_diodes_orientation=state.optimize_diodes_orientation,
        route_rows_and_columns=state.route_rows_and_columns,
        additional_elements=state.additional_elements,
        generate_outline=state.generate_outline,
        outline_delta=state.outline_delta,
        template_path=state.template_path,
        create_from_annotated_layout=False,
        switch_footprint="",
        diode_footprint="",
    )
    return run(settings)
