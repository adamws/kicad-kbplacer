from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Type

import pcbnew

from .kle_serial import ViaKeyboard

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
        *,
        switch_footprint: str,
        diode_footprint: str,
    ) -> None:
        self.switch_footprint = Footprint.from_str(switch_footprint)
        self.diode_footprint = Footprint.from_str(diode_footprint)

        self.board = pcbnew.CreateEmptyBoard()
        self.nets: dict[str, pcbnew.NETINFO_ITEM] = {}
        self.net_info = self.board.GetNetInfo()
        self.net_count = self.board.GetNetCount()

    def add_footprint(self, footprint: pcbnew.FOOTPRINT) -> pcbnew.FOOTPRINT:
        logger.info(f"Add {footprint.GetReference()} footprint")
        self.board.Add(footprint)
        return footprint

    def add_switch_footprint(self, ref_count: int) -> pcbnew.FOOTPRINT:
        f = self.switch_footprint.load()
        f.SetReference(f"SW{ref_count}")
        return self.add_footprint(f)

    def add_diode_footprint(self, ref_count: int) -> pcbnew.FOOTPRINT:
        f = self.diode_footprint.load()
        f.SetReference(f"D{ref_count}")
        return self.add_footprint(f)

    def add_net(self, netname: str) -> pcbnew.NETINFO_ITEM:
        """Add new net with netname if it does not exist already"""
        if netname in self.nets:
            net = self.nets[netname]
        else:
            net = pcbnew.NETINFO_ITEM(self.board, netname, self.net_count)
            self.net_info.AppendNet(net)
            logger.info(f"Add {netname} net")
            self.board.Add(net)
            self.net_count += 1
            self.nets[netname] = net
        return net

    def create_board(self, keyboard: ViaKeyboard) -> pcbnew.BOARD:
        current_ref = 1

        for key in keyboard.keys:
            row, column = key.labels[0].split(",")

            switch = self.add_switch_footprint(current_ref)
            diode = self.add_diode_footprint(current_ref)

            net = self.add_net(f"COL{column}")
            switch.FindPadByNumber("1").SetNet(net)

            net = self.add_net(f"ROW{row}")
            diode.FindPadByNumber("1").SetNet(net)

            net = self.add_net(f"Net-(D{current_ref})-Pad2")
            switch.FindPadByNumber("2").SetNet(net)
            diode.FindPadByNumber("2").SetNet(net)

            current_ref += 1

        return self.board
