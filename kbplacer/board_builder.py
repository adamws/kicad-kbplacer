# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from string import ascii_lowercase
from typing import Dict, List, Tuple, Type, Union

import pcbnew

from .board_modifier import KICAD_VERSION
from .kle_serial import Keyboard, MatrixAnnotatedKeyboard, get_keyboard

logger = logging.getLogger(__name__)


@dataclass
class Footprint:
    libname: str
    name: str

    @classmethod
    def from_str(cls: Type[Footprint], arg: str) -> Footprint:
        parts = arg.rsplit(":", 1)
        if len(parts) != 2:
            msg = f"Unexpected footprint value: `{arg}`"
            raise RuntimeError(msg)
        return Footprint(libname="".join(parts[0]), name=parts[1])

    def load(self) -> pcbnew.FOOTPRINT:
        return pcbnew.FootprintLoad(self.libname, self.name)


class BoardBuilder:
    def __init__(
        self,
        board_path: Union[str, os.PathLike],
        *,
        switch_footprint: str,
        diode_footprint: str,
    ) -> None:
        self.switch_footprint = Footprint.from_str(switch_footprint)
        self.diode_footprint = Footprint.from_str(diode_footprint)

        # use `NewBoard` over `CreateNewBoard` because it respects netclass
        # settings from .kicad_pro file if it already exist
        self.board = pcbnew.NewBoard(board_path)
        self.nets: dict[str, pcbnew.NETINFO_ITEM] = {}
        self.net_info = self.board.GetNetInfo()
        self.net_count = self.board.GetNetCount()

    def add_footprint(self, footprint: pcbnew.FOOTPRINT) -> pcbnew.FOOTPRINT:
        logger.info(f"Add {footprint.GetReference()} footprint")
        self.board.Add(footprint)
        return footprint

    def add_switch_footprint(self, ref: str) -> pcbnew.FOOTPRINT:
        f = self.switch_footprint.load()
        f.SetReference(ref)
        return self.add_footprint(f)

    def add_diode_footprint(self, ref: str) -> pcbnew.FOOTPRINT:
        f = self.diode_footprint.load()
        f.SetReference(ref)
        return self.add_footprint(f)

    def add_net(self, netname: str) -> pcbnew.NETINFO_ITEM:
        """Add new net with netname if it does not exist already"""
        if netname in self.nets:
            net = self.nets[netname]
        else:
            net = pcbnew.NETINFO_ITEM(self.board, netname, self.net_count)
            if KICAD_VERSION < (8, 0, 0):
                self.net_info.AppendNet(net)
            logger.info(f"Add {netname} net")
            self.board.Add(net)
            self.net_count += 1
            self.nets[netname] = net
        return net

    def create_board(
        self,
        keyboard: Union[str, os.PathLike, MatrixAnnotatedKeyboard],
    ) -> pcbnew.BOARD:
        if isinstance(keyboard, str) or isinstance(keyboard, os.PathLike):
            with open(keyboard, "r", encoding="utf-8") as f:
                layout = json.load(f)
                tmp: Keyboard = get_keyboard(layout)
                if not isinstance(tmp, MatrixAnnotatedKeyboard):
                    try:
                        _keyboard = MatrixAnnotatedKeyboard(tmp.meta, tmp.keys)
                    except Exception as e:
                        msg = (
                            f"Layout from {keyboard} is not convertible to "
                            "matrix annotated keyboard which is required "
                            "for board create"
                        )
                        raise RuntimeError(msg) from e
                else:
                    _keyboard = tmp
        else:
            _keyboard: MatrixAnnotatedKeyboard = keyboard

        _keyboard.collapse()

        current_ref = 1
        items: List[Tuple[str, str]] = []
        key_iterator = _keyboard.key_iterator(ignore_alternative=False)

        for key in key_iterator:
            if key.decal:
                continue
            items.append(MatrixAnnotatedKeyboard.get_matrix_position(key))

        def _sort_matrix(item: Tuple[str, str]) -> Tuple[int, int]:
            row_match = re.search(r"\d+", item[0])
            column_match = re.search(r"\d+", item[1])

            if row_match is None or column_match is None:
                msg = f"No numeric part for row or column found in '{item}'"
                raise ValueError(msg)

            return int(row_match.group()), int(column_match.group())

        progress: Dict[Tuple[str, str], List[pcbnew.FOOTPRINT]] = defaultdict(list)
        for row, column in sorted(items, key=_sort_matrix):
            position = (row, column)
            if position not in progress:
                switch = self.add_switch_footprint(f"SW{current_ref}")
                diode = self.add_diode_footprint(f"D{current_ref}")

                column_name = f"COL{column}" if column.isdigit() else column
                net = self.add_net(column_name)
                switch.FindPadByNumber("1").SetNet(net)

                row_name = f"ROW{row}" if row.isdigit() else row
                net = self.add_net(row_name)
                diode.FindPadByNumber("1").SetNet(net)

                net = self.add_net(f"Net-(D{current_ref})-Pad2")
                switch.FindPadByNumber("2").SetNet(net)
                diode.FindPadByNumber("2").SetNet(net)

                current_ref += 1
                progress[position].append(switch)
            else:
                # this must be alternative layout key, do not need to create nets
                # or add diode for it. Just add duplicate and add suffix to reference
                switches = progress[position]
                default_switch = switches[0]

                suffix = ascii_lowercase[len(switches) - 1]
                switch = pcbnew.Cast_to_FOOTPRINT(default_switch.Duplicate())
                switch.SetReference(default_switch.GetReference() + suffix)
                self.add_footprint(switch)

                progress[position].append(switch)

        return self.board
