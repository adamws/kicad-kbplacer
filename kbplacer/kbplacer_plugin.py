from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import pcbnew

from .board_builder import BoardBuilder
from .edge_generator import build_board_outline
from .element_position import ElementInfo
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
    route_rows_and_columns: bool
    additional_elements: List[ElementInfo]
    generate_outline: bool
    outline_delta: float
    template_path: str
    create_from_annotated_layout: bool
    switch_footprint: str
    diode_footprint: str


def run(settings: PluginSettings) -> pcbnew.BOARD:
    if settings.create_from_annotated_layout:
        builder = BoardBuilder(
            switch_footprint=settings.switch_footprint,
            diode_footprint=settings.diode_footprint,
        )
        board = builder.create_board(settings.layout_path)
        board.Save(settings.board_path)

    board = pcbnew.LoadBoard(settings.board_path)

    placer = KeyPlacer(board, settings.key_distance)
    placer.run(
        settings.layout_path,
        settings.key_info,
        settings.diode_info,
        settings.route_switches_with_diodes,
        settings.route_rows_and_columns,
        additional_elements=settings.additional_elements,
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
