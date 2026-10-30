"""SWIG reference (KiCad 10): what kbplacer's own transforms produce for SW1 of examples/2x2."""

import json
import sys

import pcbnew

sys.path.insert(0, "/repo")
from kbplacer.board_modifier import get_footprint, set_rotation, set_side  # noqa: E402
from kbplacer.element_position import Side  # noqa: E402


def pads(fp):
    return {p.GetNumber(): (p.GetPosition().x, p.GetPosition().y) for p in fp.Pads()}


out = {"version": pcbnew.Version()}
for case in ["rotate90", "back", "back_then_rotate90"]:
    board = pcbnew.LoadBoard("/repo/examples/2x2/keyboard-before.kicad_pcb")
    fp = get_footprint(board, "SW1")
    if case == "rotate90":
        set_rotation(fp, 90)
    elif case == "back":
        set_side(fp, Side.BACK)
    else:
        set_side(fp, Side.BACK)
        set_rotation(fp, 90)
    out[case] = {
        "orientation": fp.GetOrientationDegrees(),
        "flipped": fp.IsFlipped(),
        "position": (fp.GetPosition().x, fp.GetPosition().y),
        "pads": pads(fp),
    }
print(json.dumps(out))
