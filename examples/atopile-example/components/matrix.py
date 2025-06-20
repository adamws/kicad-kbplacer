import re
import json
import logging
from pathlib import Path
from typing import List, Tuple, Union, Dict
from collections import defaultdict

import faebryk.library._F as F
from faebryk.core.module import Module
from faebryk.exporters.pcb.layout.absolute import LayoutAbsolute
from faebryk.exporters.pcb.layout.typehierarchy import LayoutTypeHierarchy
from faebryk.exporters.pcb.routing.util import Path
from faebryk.libs.library import L
from faebryk.libs.util import times

from kbplacer.kle_serial import Key, MatrixAnnotatedKeyboard, get_keyboard

logger = logging.getLogger(__name__)


class SwitchDiode(Module):
    # in_: F.ElectricSignal
    # out_: F.ElectricSignal
    switch = L.f_field(F.Switch(F.Electrical))()
    diode: F.Diode

    def __init__(self, x, y) -> None:
        super().__init__()
        print(f"__init__ SwitchDiode: {x=} {y=}")
        self.x = x
        self.y = y

    def __preinit__(self) -> None:
        print(f"__preinit__ SwitchDiode: {self.x=} {self.y=}")
        # self.out_.line.connect_via(
        #    [self.switch, self.diode], self.out_.reference.lv
        # )

        self.diode.anode.connect(self.switch.unnamed[1])

        fp = F.KicadFootprint(pin_names=["1", "2"])
        fp.add(F.KicadFootprint.has_kicad_identifier("marbastlib-mx:SW_MX_1u"))
        self.switch.attach_to_footprint.attach(fp)

        diode_fp = F.KicadFootprint(pin_names=["1", "2"])
        diode_fp.add(F.KicadFootprint.has_kicad_identifier("Diode_SMD:D_SOD-123"))

        self.diode.add(
            F.can_attach_to_footprint_via_pinmap(
                {
                    "1": self.diode.cathode,
                    "2": self.diode.anode,
                }
            )
        )
        self.diode.get_trait(F.can_attach_to_footprint).attach(diode_fp)

        Point = F.has_pcb_position.Point
        Ly = F.has_pcb_position.layer_type
        self.add(F.has_pcb_position_defined(Point((self.x, self.y, 0, Ly.NONE))))

    # @L.rt_field
    # def has_pcb_position_defined(self):
    #    Point = F.has_pcb_position.Point
    #    Ly = F.has_pcb_position.layer_type
    #    print("HAS PCB POSITION")
    #    return Point((50, 50, 0, Ly.NONE))

    @L.rt_field
    def has_defined_layout(self):
        Point = F.has_pcb_position.Point
        Ly = F.has_pcb_position.layer_type

        layout = LayoutTypeHierarchy(
            layouts=[
                LayoutTypeHierarchy.Level(
                    mod_type=F.Switch(F.Electrical),
                    layout=LayoutAbsolute(Point((0, 0, 0, Ly.TOP_LAYER))),
                ),
                LayoutTypeHierarchy.Level(
                    mod_type=F.Diode,
                    layout=LayoutAbsolute(Point((5.08, 4, 90, Ly.BOTTOM_LAYER))),
                ),
            ]
        )
        return F.has_pcb_layout_defined(layout)

    @L.rt_field
    def pcb_routing_stategy_manual(self):
        return F.has_pcb_routing_strategy_manual(
            [
                (
                    [self.diode.anode, self.switch.unnamed[1]],
                    Path(
                        [
                            Path.Track(
                                0.2,
                                "B.Cu",
                                [
                                    (2.54, -5.08),
                                    (2.54, -0.19),
                                    (5.08, 2.35),
                                ],
                            ),
                        ]
                    ),
                ),
            ]
        )


def load_keyboard(layout_path) -> MatrixAnnotatedKeyboard:
    with open(layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)
        _keyboard = get_keyboard(layout)
        _keyboard = MatrixAnnotatedKeyboard.from_keyboard(_keyboard)
        _keyboard.collapse()
        return _keyboard


def parse_annotation(annotation: str) -> int:
    pattern = r"^([A-Za-z]*)(\d+)$"

    match = re.match(pattern, annotation)
    if match:
        _, digits = match.groups()
        return int(digits)
    msg = "Unexpected annotation format"
    raise RuntimeError(msg)


class KeyboardMatrix(Module):

    @L.rt_field
    def rows(self):
        return times(len(self._rows), lambda: F.Electrical())

    @L.rt_field
    def columns(self):
        return times(len(self._columns), lambda: F.Electrical())

    @L.rt_field
    def switches(self):
        def _int(value: float) -> Union[int, float]:
            return int(value) if int(value) == value else value

        def _key_center(key: Key) -> Tuple[Union[int, float], Union[int, float]]:
            return (_int(key.x + key.width / 2), _int(key.y + key.height / 2))

        positions = [_key_center(k) for _, _, k in self.switch_data]
        return [SwitchDiode(19.05 * x, 19.05 * y) for x, y in positions]

    def __init__(self, layout_path: str) -> None:
        super().__init__()
        keyboard = load_keyboard(layout_path)
        keys = keyboard.keys_in_matrix_order()

        self._rows = set()
        self._columns = set()
        self.switch_data: List[Tuple[int, int, Key]] = []
        for key in keys:
            col_str, row_str = MatrixAnnotatedKeyboard.get_matrix_position(key)
            position = parse_annotation(col_str), parse_annotation(row_str)
            self._rows.add(position[0])
            self._columns.add(position[1])
            self.switch_data.append((*position, key))


    def __preinit__(self):
        for i, data in enumerate(self.switch_data):
            row, column, _ = data 
            # this won't work if there are row/columns missing
            self.columns[column].connect(self.switches[i].switch.unnamed[0])
            self.rows[row].connect(self.switches[i].diode.cathode)

