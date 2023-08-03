from __future__ import annotations

import argparse
import copy
import json
import pprint

from dataclasses import asdict, dataclass, field, fields
from typing import Any, List, Optional


@dataclass
class KeyDefault:
    textColor: str = "#000000"
    textSize: int = 3


@dataclass
class Key:
    color: str = "#cccccc"
    labels: List[str] = field(default_factory=list)
    textColor: List[Optional[str]] = field(default_factory=list)
    textSize: List[Optional[int]] = field(default_factory=list)
    default: KeyDefault = field(default_factory=KeyDefault)
    x: float = 0
    y: float = 0
    width: float = 1
    height: float = 1
    x2: float = 0
    y2: float = 0
    width2: float = 1
    height2: float = 1
    rotation_x: float = 0
    rotation_y: float = 0
    rotation_angle: float = 0
    decal: bool = False
    ghost: bool = False
    stepped: bool = False
    nub: bool = False
    profile: str = ""
    sm: str = ""  # switch mount
    sb: str = ""  # switch brand
    st: str = ""  # switch type

    def __post_init__(self):
        if isinstance(self.default, dict):
            self.default = KeyDefault(**self.default)


@dataclass
class Background:
    name: str = ""
    style: str = ""


@dataclass
class KeyboardMetadata:
    author: str = ""
    backcolor: str = "#eeeeee"
    background: Optional[Background] = None
    name: str = ""
    notes: str = ""
    radii: str = ""
    switchBrand: str = ""
    switchMount: str = ""
    switchType: str = ""

    def __post_init__(self):
        if isinstance(self.background, dict):
            self.background = Background(**self.background)


@dataclass
class Keyboard:
    meta: KeyboardMetadata = field(default_factory=KeyboardMetadata)
    keys: List[Key] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict) -> Keyboard:
        if isinstance(data["meta"], dict):
            data["meta"] = KeyboardMetadata(**data["meta"])
        if isinstance(data["keys"], list):
            keys: List[Key] = []
            for key in data["keys"]:
                keys.append(Key(**key))
            data["keys"] = keys
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(asdict(self))


# Map from serialized label position to normalized position,
# depending on the alignment flags.
# fmt: off
LABEL_MAP: List[List[int]] = [
    # 0  1  2  3  4  5  6  7  8  9 10 11   # align flags
    [ 0, 6, 2, 8, 9,11, 3, 5, 1, 4, 7,10], # 0 = no centering
    [ 1, 7,-1,-1, 9,11, 4,-1,-1,-1,-1,10], # 1 = center x
    [ 3,-1, 5,-1, 9,11,-1,-1, 4,-1,-1,10], # 2 = center y
    [ 4,-1,-1,-1, 9,11,-1,-1,-1,-1,-1,10], # 3 = center x & y
    [ 0, 6, 2, 8,10,-1, 3, 5, 1, 4, 7,-1], # 4 = center front (default)
    [ 1, 7,-1,-1,10,-1, 4,-1,-1,-1,-1,-1], # 5 = center front & x
    [ 3,-1, 5,-1,10,-1,-1,-1, 4,-1,-1,-1], # 6 = center front & y
    [ 4,-1,-1,-1,10,-1,-1,-1,-1,-1,-1,-1], # 7 = center front & x & y
]
# fmt: on


def reorder_labels(labels, align):
    ret: List[Any] = 12 * [None]
    for i, label in enumerate(labels):
        if label:
            index = LABEL_MAP[align][i]
            ret[index] = label
    while ret and ret[-1] is None:
        ret.pop()
    return ret


def cleanup_key(key: Key):
    for attribute_name in ["textSize", "textColor"]:
        attribute = getattr(key, attribute_name)
        attribute = attribute[0 : len(key.labels)]
        for i, (label, val) in enumerate(zip(key.labels, attribute)):
            if not label:
                attribute[i] = None
            if val == getattr(key.default, attribute_name):
                attribute[i] = None
        while attribute and attribute[-1] is None:
            attribute.pop()
        setattr(key, attribute_name, attribute)


def parse(layout) -> Keyboard:
    if not isinstance(layout, list):
        msg = "Expected an list of objects"
        raise RuntimeError(msg)

    metadata: KeyboardMetadata = KeyboardMetadata()
    rows: List[Any] = layout
    current: Key = Key()

    if len(rows) == 0:
        msg = "Expected at least one row of keys"
        raise RuntimeError(msg)

    keys = []
    cluster = {"x": 0, "y": 0}
    align = 4

    for r, row in enumerate(rows):
        if isinstance(row, list):
            for k, item in enumerate(row):
                if isinstance(item, str):
                    new_key = copy.deepcopy(current)
                    # Calculate some generated values
                    new_key.width2 = (
                        current.width if new_key.width2 == 0 else current.width2
                    )
                    new_key.height2 = (
                        current.height if new_key.height2 == 0 else current.height2
                    )
                    new_key.labels = reorder_labels(item.split("\n"), align)
                    new_key.textSize = reorder_labels(new_key.textSize, align)

                    cleanup_key(new_key)

                    keys.append(new_key)

                    current.x += current.width
                    current.width = 1
                    current.height = 1
                    current.x2 = 0
                    current.y2 = 0
                    current.width2 = 0
                    current.height2 = 0
                    current.nub = False
                    current.stepped = False
                    current.decal = False
                elif isinstance(item, dict):
                    if k != 0 and ("r" in item or "rx" in item or "ry" in item):
                        msg = (
                            "Rotation can only be specified on the first key in the row"
                        )
                        raise RuntimeError(msg)
                    if "r" in item:
                        current.rotation_angle = item["r"]
                    if "rx" in item:
                        cluster["x"] = item["rx"]
                        current.x = cluster["x"]
                        current.y = cluster["y"]
                        current.rotation_x = item["rx"]
                    if "ry" in item:
                        cluster["y"] = item["ry"]
                        current.x = cluster["x"]
                        current.y = cluster["y"]
                        current.rotation_y = item["ry"]
                    if "a" in item:
                        align = item["a"]
                    if "f" in item:
                        current.default.textSize = item["f"]
                        current.textSize = []
                    if "f2" in item:
                        if len(current.textSize) == 0:
                            current.textSize = [None]
                        for _ in range(1, 12):
                            current.textSize.append(item["f2"])
                    if "fa" in item:
                        current.textSize = item["fa"]
                    if "p" in item:
                        current.profile = item["p"]
                    if "c" in item:
                        current.color = item["c"]
                    if "t" in item:
                        split = item["t"].split("\n")
                        if split[0]:
                            current.default.textColor = split[0]
                        current.textColor = reorder_labels(split, align)
                    if "x" in item:
                        current.x += item["x"]
                    if "y" in item:
                        current.y += item["y"]
                    if "w" in item:
                        current.width = item["w"]
                        current.width2 = item["w"]
                    if "h" in item:
                        current.height = item["h"]
                        current.height2 = item["h"]
                    if "x2" in item:
                        current.x2 = item["x2"]
                    if "y2" in item:
                        current.y2 = item["y2"]
                    if "w2" in item:
                        current.width2 = item["w2"]
                    if "h2" in item:
                        current.height2 = item["h2"]
                    if "n" in item:
                        current.nub = item["n"]
                    if "l" in item:
                        current.stepped = item["l"]
                    if "d" in item:
                        current.decal = item["d"]
                    if "g" in item:
                        current.ghost = item["g"]
                    if "sm" in item:
                        current.sm = item["sm"]
                    if "sb" in item:
                        current.sb = item["sb"]
                    if "st" in item:
                        current.st = item["st"]
                else:
                    msg = "Unexpected item type"
                    raise RuntimeError(msg)

            # end of the row:
            current.y += 1
            current.x = current.rotation_x
        elif isinstance(row, dict) and r == 0:
            field_set = {f.name for f in fields(KeyboardMetadata) if f.init}
            row_filtered = {k: v for k, v in row.items() if k in field_set}
            metadata = KeyboardMetadata(**row_filtered)
        else:
            msg = "Unexpected"
            raise RuntimeError(msg)

    return Keyboard(meta=metadata, keys=keys)


def get_keyboard(layout: dict) -> Keyboard:
    try:
        return parse(layout)
    except Exception:
        pass
    try:
        return Keyboard.from_json(layout)
    except Exception:
        pass
    msg = "Unable to get keyboard layout"
    raise RuntimeError(msg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KLE format converter")
    parser.add_argument(
        "-i", "--input", required=True, help="Raw json layout definition file"
    )

    args = parser.parse_args()
    input_path = args.input

    with open(input_path, "r") as f:
        text_input = f.read()
        layout = json.loads(text_input)
        result = parse(layout)
        result_json = json.loads(result.to_json())
        pprint.pprint(result_json)
