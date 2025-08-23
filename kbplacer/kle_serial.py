# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import pprint
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field, fields
from enum import Enum, auto
from itertools import chain
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type, Union

logger = logging.getLogger(__name__)

DEFAULT_KEY_COLOR = "#cccccc"
DEFAULT_TEXT_COLOR = "#000000"
DEFAULT_TEXT_SIZE = 3
KEY_MAX_LABELS = 12

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

REVERSE_LABEL_MAP: List[List[int]] = [
    # 0  1  2  3  4  5  6  7  8  9 10 11   # align flags
    [ 0, 8, 2, 6, 9, 7, 1,10, 3, 4,11, 5], # 0 = no centering
    [-1, 0,-1,-1, 6,-1,-1, 1,-1, 4,11, 5], # 1 = center x
    [-1,-1,-1, 0, 8, 2,-1,-1,-1, 4,11, 5], # 2 = center y
    [-1,-1,-1,-1, 0,-1,-1,-1,-1, 4,11, 5], # 3 = center x & y
    [ 0, 8, 2, 6, 9, 7, 1,10, 3,-1, 4,-1], # 4 = center front (default)
    [-1, 0,-1,-1, 6,-1,-1, 1,-1,-1, 4,-1], # 5 = center front & x
    [-1,-1,-1, 0, 8, 2,-1,-1,-1,-1, 4,-1], # 6 = center front & y
    [-1,-1,-1,-1, 0,-1,-1,-1,-1,-1, 4,-1], # 7 = center front & x & y
]
# fmt: on


@dataclass
class KeyDefault:
    textColor: str = DEFAULT_TEXT_COLOR  # noqa: N815
    textSize: int = DEFAULT_TEXT_SIZE  # noqa: N815


@dataclass
class Key:
    color: str = DEFAULT_KEY_COLOR
    labels: List[Optional[str]] = field(default_factory=list)
    textColor: List[Optional[str]] = field(default_factory=list)  # noqa: N815
    textSize: List[Optional[int]] = field(default_factory=list)  # noqa: N815
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

    def __post_init__(self: Key) -> None:
        if isinstance(self.default, dict):
            self.default = KeyDefault(**self.default)
        for key_field in self.__dataclass_fields__:
            value = getattr(self, key_field)
            if isinstance(value, float):
                new_val = round(value, 6)
                setattr(self, key_field, new_val)

    def get_label(self: Key, index: int) -> Optional[str]:
        if len(self.labels) > index:
            return self.labels[index]
        return None

    def set_label(self: Key, index: int, value: str) -> None:
        if index > KEY_MAX_LABELS - 1 or index < 0:
            msg = "Illegal key label index"
            raise RuntimeError(msg)
        labels_to_add = index + 1 - len(self.labels)
        self.labels += labels_to_add * [None]
        self.labels[index] = value


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
    switchBrand: str = ""  # noqa: N815
    switchMount: str = ""  # noqa: N815
    switchType: str = ""  # noqa: N815

    def __post_init__(self: KeyboardMetadata) -> None:
        if isinstance(self.background, dict):
            self.background = Background(**self.background)


@dataclass
class Keyboard:
    meta: KeyboardMetadata = field(default_factory=KeyboardMetadata)
    keys: List[Key] = field(default_factory=list)

    @classmethod
    def from_json(cls: Type[Keyboard], data: dict) -> Keyboard:
        if isinstance(data["meta"], dict):
            data["meta"] = KeyboardMetadata(**data["meta"])
        if isinstance(data["keys"], list):
            keys: List[Key] = [Key(**key) for key in data["keys"]]
            data["keys"] = keys
        return cls(**data)

    def to_json(self: Keyboard, indent: Optional[int] = None) -> str:
        return json.dumps(asdict(self), indent=indent)

    def __text_size_changed(self: Keyboard, current: list[Any], new: list[Any]) -> bool:
        current = copy.copy(current)
        new = copy.copy(new)
        for obj in [current, new]:
            if len_difference := KEY_MAX_LABELS - len(obj):
                obj.extend(len_difference * [0])
        return current != new

    def to_kle(self: Keyboard) -> str:
        row = []
        rows = []

        current: Key = copy.deepcopy(Key())
        # some properties are not part of Key type, store them separately:
        current_alignment = 4
        current_f2 = -1
        # rotation origin:
        cluster: dict[str, float] = {"r": 0, "rx": 0, "ry": 0}

        new_row = True
        current.y -= 1  # will be incremented on first row

        for key in self.keys:
            props: dict[str, Any] = {}

            def add_prop(name: str, value: Any, default: Any) -> Any:
                def _round(v: Any) -> Any:
                    return round(v, 6) if isinstance(v, float) else v

                value = _round(value)
                default = _round(default)
                if value != default:
                    props[name] = value
                return value

            if key.labels:
                alignment, labels = find_best_label_alignment(key.labels)
            else:
                alignment, labels = 7, []

            # detect new row
            new_cluster = (
                key.rotation_angle != cluster["r"]
                or key.rotation_x != cluster["rx"]
                or key.rotation_y != cluster["ry"]
            )
            new_row = key.y != current.y
            if row and (new_cluster or new_row):
                # push the old row
                rows.append(row)
                row = []
                new_row = True

            if new_row:
                current.y = round(current.y + 1, 6)
                # 'y' is reset if either 'rx' or 'ry' are changed
                if key.rotation_y != cluster["ry"] or key.rotation_x != cluster["rx"]:
                    current.y = key.rotation_y
                # always reset x to rx (which defaults to zero)
                current.x = key.rotation_x

                cluster["r"] = key.rotation_angle
                cluster["rx"] = key.rotation_x
                cluster["ry"] = key.rotation_y

                new_row = False

            current.rotation_angle = add_prop(
                "r", key.rotation_angle, current.rotation_angle
            )
            current.rotation_x = add_prop("rx", key.rotation_x, current.rotation_x)
            current.rotation_y = add_prop("ry", key.rotation_y, current.rotation_y)

            x_offset = add_prop("x", round(key.x - current.x, 6), 0)
            y_offset = add_prop("y", round(key.y - current.y, 6), 0)
            current.x = round(current.x + key.width + x_offset, 6)
            current.y = round(current.y + y_offset, 6)

            current.color = add_prop("c", key.color, current.color)
            if text_color := reorder_items_kle(key.textColor, alignment):
                if not text_color[0]:
                    text_color[0] = key.default.textColor
                text_color = ["" if not item else item for item in text_color]
                text_color = "\n".join(text_color).rstrip("\n")
                current.textColor = add_prop("t", text_color, current.textColor)
            else:
                current.default.textColor = add_prop(
                    "t", key.default.textColor, current.default.textColor
                )

            current.ghost = add_prop("g", key.ghost, current.ghost)
            current.profile = add_prop("p", key.profile, current.profile)
            current.sm = add_prop("sm", key.sm, current.sm)
            current.sb = add_prop("sb", key.sb, current.sb)
            current.st = add_prop("st", key.st, current.st)

            current_alignment = add_prop("a", alignment, current_alignment)
            current.default.textSize = add_prop(
                "f", key.default.textSize, current.default.textSize
            )
            if "f" in props:
                current.textSize = []

            text_size = reorder_items_kle(key.textSize, alignment)
            text_size = [0 if not isinstance(i, int) else i for i in text_size]
            if self.__text_size_changed(current.textSize, text_size):
                if not text_size:
                    current.default.textSize = add_prop(
                        "f", key.default.textSize, current.default.textSize
                    )
                    current.textSize = []
                else:
                    if optimize := not text_size[0]:
                        optimize = all(x == text_size[1] for x in text_size[2:])
                    if optimize:
                        f2 = text_size[1]
                        current_f2 = add_prop("f2", f2, current_f2)
                        # don't know why this gives type checking error, works fine:
                        current.textSize = [0] + (11 * [f2])  # type: ignore
                    else:
                        current.textSize = add_prop("fa", text_size, [])

            add_prop("w", key.width, 1)
            add_prop("h", key.height, 1)
            add_prop("w2", key.width2, key.width)
            add_prop("h2", key.height2, key.height)
            add_prop("x2", key.x2, 0)
            add_prop("y2", key.y2, 0)
            add_prop("l", key.stepped, False)
            add_prop("n", key.nub, False)
            add_prop("d", key.decal, False)

            if props:
                row.append(props)

            current.labels = labels
            labels = ["" if not item else item for item in labels]
            row.append("\n".join(labels).rstrip("\n"))

        if row:
            rows.append(row)

        result = ""

        default_meta = asdict(KeyboardMetadata())
        meta = copy.deepcopy(asdict(self.meta))
        if meta != default_meta:
            # include only non-default meta fields
            for k in list(meta.keys()):
                if default_meta.get(k, None) == meta[k]:
                    del meta[k]
            result += json.dumps(meta, indent=None) + ",\n"

        for row in rows:
            result += json.dumps(row, indent=None) + ",\n"
        result = result.strip(",\n")
        return result


@dataclass
class MatrixAnnotatedKeyboard(Keyboard):
    MATRIX_COORDINATES_LABEL = 0
    LAYOUT_OPTION_LABEL = 8

    alternative_keys: List[Key] = field(default_factory=list)
    collapsed: bool = field(init=False)

    def __post_init__(self: MatrixAnnotatedKeyboard) -> None:
        positions = []
        for key in list(self.keys):
            if not key.decal:
                # check if required labels defined correctly
                position = MatrixAnnotatedKeyboard.get_matrix_position(key)
                option = MatrixAnnotatedKeyboard.get_layout_option(key)
                if option == 0:
                    positions.append(position)
            if self.__is_alternative(key):
                self.alternative_keys.append(copy.deepcopy(key))
                self.keys.remove(key)
        # check if there are no duplicated matrix position in default key group
        if len(positions) != len(set(positions)):
            msg = "Duplicate matrix position for default layout keys not allowed"
            raise ValueError(msg)

        self.collapsed = False

    def __is_alternative(self, key: Key) -> bool:
        if label := key.get_label(self.LAYOUT_OPTION_LABEL):
            # check if not default layout:
            if label.split(",")[1].strip() != "0":
                # alternative layout key
                return True
        return False

    def key_iterator(self, *, ignore_alternative: bool) -> Iterator[Key]:
        if ignore_alternative:
            return iter(self.keys)
        else:
            return chain(self.keys, self.alternative_keys)

    def _get_layout_option_or_none(self, key: Key) -> Optional[Tuple[int, int]]:
        if label := key.get_label(self.LAYOUT_OPTION_LABEL):
            parts = label.split(",")
            if len(parts) != 2:
                msg = "Unexpected number of ',' delimited elements in key label"
                raise ValueError(msg)
            return int(parts[0]), int(parts[1])
        return None

    def _get_layout_options(self) -> Dict[int, Dict[int, List[Key]]]:
        keys: Dict[int, Dict[int, List[Key]]] = defaultdict(lambda: defaultdict(list))
        for key in self.key_iterator(ignore_alternative=False):
            option = self._get_layout_option_or_none(key)
            if option:
                keys[option[0]][option[1]].append(key)
        return keys

    @staticmethod
    def _key_matrix_position(key: Key) -> Tuple[int, int, int]:
        matrix_position = MatrixAnnotatedKeyboard.get_matrix_position(key)
        row_match = re.search(r"\d+", matrix_position[0])
        column_match = re.search(r"\d+", matrix_position[1])

        if row_match is None or column_match is None:
            msg = f"No numeric part for row or column found in '{matrix_position}'"
            raise ValueError(msg)

        return (
            int(row_match.group()),
            int(column_match.group()),
            MatrixAnnotatedKeyboard.get_layout_option(key),
        )

    def collapse(self) -> None:
        """Modify positions of alternative_keys to destination positions
        i.e. the positions they would take as 'non alternative'
        and de-duplicate items with equal matrix coordinates and size
        """
        if self.collapsed:
            # prevent double collapsing
            return

        seen = {}
        new_alternatives = []

        def _int(value: float) -> Union[int, float]:
            return int(value) if int(value) == value else value

        def _key_center(key: Key) -> Tuple[Union[int, float], Union[int, float]]:
            return (_int(key.x + key.width / 2), _int(key.y + key.height / 2))

        def _key_props(key: Key):
            props = (
                key.labels[self.MATRIX_COORDINATES_LABEL],
                *_key_center(key),
                key.decal,
            )
            return props

        for k in self.keys:
            # ignore decals in default key group
            if k.decal:
                continue
            seen[_key_props(k)] = True

        layout_keys = self._get_layout_options()
        for choices in layout_keys.values():
            anchor = min(choices[0], key=lambda key: (key.x, key.y))
            for choice, keys in choices.items():
                if choice != 0:
                    group_anchor = min(keys, key=lambda key: (key.x, key.y))
                    move_x = anchor.x - group_anchor.x
                    move_y = anchor.y - group_anchor.y
                    for k in keys:
                        k.x = _int(k.x + move_x)
                        k.y = _int(k.y + move_y)
                        props = _key_props(k)
                        if props not in seen:
                            seen[props] = True
                            new_alternatives.append(k)

        for key in list(new_alternatives):
            if key.decal:
                new_alternatives.remove(key)

        self.alternative_keys = new_alternatives
        self.collapsed = True

    def sort_keys(self) -> None:
        for l in [self.keys, self.alternative_keys]:
            l.sort(key=lambda k: MatrixAnnotatedKeyboard._key_matrix_position(k))

    def keys_in_matrix_order(self) -> List[Key]:
        """Returns keys in matrix row/column order. If multiple keys occupy same
        matrix position, sort by layout option label. Ignores decal keys.
        """
        items: List[Key] = []
        for key in self.key_iterator(ignore_alternative=False):
            if key.decal:
                continue
            items.append(key)

        return sorted(
            items, key=lambda k: MatrixAnnotatedKeyboard._key_matrix_position(k)
        )

    @staticmethod
    def get_matrix_position(key: Key) -> Tuple[str, str]:
        try:
            label = key.get_label(MatrixAnnotatedKeyboard.MATRIX_COORDINATES_LABEL)
            split = str(label).split(",")
            if len(split) != 2:
                raise RuntimeError
            return (split[0].strip(), split[1].strip())
        except Exception as e:
            msg = "Matrix coordinates label missing or invalid"
            raise RuntimeError(msg) from e

    @staticmethod
    def get_layout_option(key: Key) -> int:
        if layout_option_label := key.get_label(
            MatrixAnnotatedKeyboard.LAYOUT_OPTION_LABEL
        ):
            return int(layout_option_label.split(",")[1])
        return 0

    def to_keyboard(self) -> Keyboard:
        return Keyboard(meta=self.meta, keys=self.keys_in_matrix_order())

    @classmethod
    def from_keyboard(cls, keyboard: Keyboard) -> MatrixAnnotatedKeyboard:
        if not isinstance(keyboard, MatrixAnnotatedKeyboard):
            try:
                converted = MatrixAnnotatedKeyboard(keyboard.meta, keyboard.keys)
                return converted
            except Exception as e:
                msg = (
                    "Keyboard object not convertible to "
                    f"matrix annotated keyboard: {e}"
                )
                raise RuntimeError(msg) from e
        return keyboard


def reorder_items(items: List[Any], align: int) -> List[Any]:
    ret: List[Any] = KEY_MAX_LABELS * [None]
    for i, item in enumerate(items):
        if item:
            index = LABEL_MAP[align][i]
            ret[index] = item
    while ret and ret[-1] is None:
        ret.pop()
    return ret


def reorder_items_kle(items, align) -> List[Any]:
    ret: List[Any] = KEY_MAX_LABELS * [None]
    for i, label in enumerate(items):
        if label:
            index = REVERSE_LABEL_MAP[align][i]
            if index == -1:
                ret = []
                break
            ret[index] = label
    while ret and ret[-1] is None:
        ret.pop()
    return ret


def find_best_label_alignment(labels) -> Tuple[int, List[Any]]:
    results = {}
    for align in reversed(range(0, 8)):
        if ret := reorder_items_kle(labels, align):
            results[align] = ret

    if results.items():
        best = min(results.items(), key=lambda x: len(x[1]))
        return best[0], best[1]
    else:
        return 0, []


def cleanup_key(key: Key) -> None:
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


def parse_qmk(layout) -> MatrixAnnotatedKeyboard:
    metadata: KeyboardMetadata = KeyboardMetadata()

    if "layouts" not in layout:
        msg = "Invalid QMK data, required 'layouts' value not found"
        raise RuntimeError(msg)

    layouts = layout["layouts"]
    keys: Dict[Tuple[int, int], List[Key]] = defaultdict(list)

    for i, layout in enumerate(layouts.values()):
        if "layout" not in layout:
            msg = "Invalid QMK data, required 'layout' value not found"
            raise RuntimeError(msg)

        for item in layout["layout"]:
            if not isinstance(item, dict):
                msg = f"Unexpected data appeared while parsing QMK layout: '{item}'"
                raise RuntimeError(msg)

            key: Key = Key()
            key.x = item["x"]
            key.y = item["y"]
            if "r" in item:
                key.rotation_angle = item["r"]
            if "rx" in item:
                key.rotation_x = item["rx"]
            if "ry" in item:
                key.rotation_y = item["ry"]
            if "w" in item:
                key.width = item["w"]
            if "h" in item:
                key.height = item["h"]

            # qmk uses 'matrix' property to define key position instead of labels
            # this is not a part of Key dataclass derived from
            # keyboard-layout-editor schema. Because we do not care about actual
            # labels (which qmk layout also can define), use approach from via
            # layouts, i.e. encode matrix position in first label
            matrix_position = item["matrix"]
            if not isinstance(matrix_position, list) or len(matrix_position) != 2:
                msg = (
                    "Unexpected key matrix position appeared while parsing QMK "
                    f"layout: '{matrix_position}'"
                )
                raise RuntimeError(msg)
            key.set_label(
                MatrixAnnotatedKeyboard.MATRIX_COORDINATES_LABEL,
                f"{matrix_position[0]},{matrix_position[1]}",
            )
            # qmk layouts do not have information about alternative layout option groups,
            # each group is 0
            key.set_label(MatrixAnnotatedKeyboard.LAYOUT_OPTION_LABEL, f"0,{i}")

            position = (matrix_position[0], matrix_position[1])
            keys[position].append(key)

    # remove duplicate keys ignoring LAYOUT_OPTION_LABEL value
    deduplicate_keys: Dict[Tuple[int, int], List[Key]] = defaultdict(list)
    for position, key_list in keys.items():
        deduplicate_position_keys: List[Key] = []
        for k in key_list:
            duplicate = False
            for k1 in deduplicate_position_keys:
                temp1 = copy.deepcopy(k)
                temp2 = copy.deepcopy(k1)
                temp1.set_label(MatrixAnnotatedKeyboard.LAYOUT_OPTION_LABEL, "")
                temp2.set_label(MatrixAnnotatedKeyboard.LAYOUT_OPTION_LABEL, "")
                if temp1 == temp2:
                    duplicate = True
                    break
            if not duplicate:
                deduplicate_position_keys.append(k)

        # clean up labels, i.e. remove LAYOUT_OPTION_LABEL if given key does not have
        # alternative value
        if len(deduplicate_position_keys) == 1:
            deduplicate_position_keys[0].labels = [
                deduplicate_position_keys[0].labels[0]
            ]

        deduplicate_keys[position] = deduplicate_position_keys

    final_keys: List[Key] = list()
    for _, l in iter(sorted(deduplicate_keys.items())):
        final_keys += l

    keyboard = MatrixAnnotatedKeyboard(meta=metadata, keys=final_keys)
    keyboard.collapsed = True
    return keyboard


def parse_via(layout) -> MatrixAnnotatedKeyboard:
    keyboard = parse_kle(layout["layouts"]["keymap"])
    return MatrixAnnotatedKeyboard(meta=keyboard.meta, keys=keyboard.keys)


def parse_kle(layout) -> Keyboard:
    if not isinstance(layout, list):
        msg = "Expected an list of objects"
        raise RuntimeError(msg)

    metadata: KeyboardMetadata = KeyboardMetadata()
    rows: List[Any] = layout
    current: Key = Key()

    if not rows:
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
                    items = item.split("\n")
                    if len(items) > KEY_MAX_LABELS:
                        msg = (
                            f"Illegal key labels: '{repr(item)}'. "
                            f"Labels string can contain {KEY_MAX_LABELS} '\\n' "
                            "separated items, ignoring redundant values."
                        )
                        logger.warning(msg)
                        items = items[0:KEY_MAX_LABELS]
                    new_key.labels = reorder_items(items, align)
                    new_key.textSize = reorder_items(new_key.textSize, align)

                    cleanup_key(new_key)

                    keys.append(new_key)

                    current.x = round(current.x + current.width, 6)
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
                        for _ in range(1, KEY_MAX_LABELS):
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
                        current.textColor = reorder_items(split, align)
                    if "x" in item:
                        current.x = round(current.x + item["x"], 6)
                    if "y" in item:
                        current.y = round(current.y + item["y"], 6)
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
            current.y = round(current.y + 1, 6)
            current.x = current.rotation_x
        elif isinstance(row, dict) and r == 0:
            field_set = {f.name for f in fields(KeyboardMetadata) if f.init}
            row_filtered = {k: v for k, v in row.items() if k in field_set}
            metadata = KeyboardMetadata(**row_filtered)
        else:
            msg = "Unexpected"
            raise RuntimeError(msg)

    return Keyboard(meta=metadata, keys=keys)


def parse_ergogen_points(layout: dict, *, zone_filter: str = "") -> Keyboard:
    if not isinstance(layout, dict):
        msg = "Expected an object with nested objects"
        raise RuntimeError(msg)
    if not layout:
        msg = "Expected non-empty object"
        raise RuntimeError(msg)

    metadata: KeyboardMetadata = KeyboardMetadata()
    keys = []

    # in ergogen terminology, 'padding' is vertical space between each key
    # and 'spread' is horizontal space between each key. These values are defined
    # in 'meta' object for each 'point' (key). Let's assume that these values are
    # the same for all of them (which I don't know if it is actually true)
    padding = None
    spread = None

    # at the end of parsing will need to fix key order, kle starts from top,
    # ergogen from bottom
    # store topmost, leftmost key index while iterating, it will be used later
    topmost_leftmost = [0, 0]

    def __int(value: float) -> Union[int, float]:
        return int(value) if int(value) == value else value

    pattern = re.compile(zone_filter) if zone_filter else None

    for name, item in layout.items():
        if pattern and not re.match(pattern, name):
            continue
        if "meta" not in item:
            msg = "Item needs to have meta defined"
            raise RuntimeError(msg)

        meta = item["meta"]

        # read key spacing only once, assume that it does not change
        if not padding and not spread:
            if "padding" not in meta or "spread" not in meta:
                msg = "Unable to determine key spacing"
                raise RuntimeError(msg)
            padding = meta["padding"]
            spread = meta["spread"]

        key = Key()

        # kle expresses distances (positions) with 1U, need to normalize
        # ergogen uses key center for position, kle uses key left top corner,
        # need to adjust position by size
        key.x = __int(item["x"] / spread)
        key.y = __int(item["y"] / padding)
        key.width = __int(meta["width"] / spread)
        key.height = __int(meta["height"] / spread)

        # non-custom key shapes (like ISO enter) not supported:
        key.width2 = key.width
        key.height2 = key.height

        if key.y > topmost_leftmost[1] or (
            key.y == topmost_leftmost[1] and key.x <= topmost_leftmost[0]
        ):
            topmost_leftmost = [key.x, key.y]

        # kle and ergogen rotate in opposite directions
        key.rotation_angle = -1 * item["r"]

        # if column_net and row_net defined, add it to label
        row = meta.get("row_net", "")
        column = meta.get("column_net", "")
        if row and column:
            key.labels.append(f"{row},{column}")
        else:
            ergogen_guide_url = "https://adamws.github.io/keyboard-pcb-design-with-ergogen-and-kbplacer/"
            msg = (
                "Ergogen layout without matrix annotations will likely produce "
                "unexpected result. For best results add `row_net` and `column_net` "
                f"metadata. For details see: {ergogen_guide_url}"
            )
            logger.warning(msg)

        keys.append(key)

    # do some cleanup to be kle compatible
    # adjust coordinates
    for key in keys:
        # reverse top-bottom
        key.y = abs(key.y - topmost_leftmost[1])
        # move position from key center (ergogen) to top left corner (kle)
        key.x = key.x - key.width / 2
        key.y = key.y - key.height / 2
    # move out of negative positions
    min_x = min(keys, key=lambda k: k.x).x
    min_x = min(0, min_x)

    min_y = min(keys, key=lambda k: k.y).y
    min_y = min(0, min_y)

    for key in keys:
        key.x = key.x - min_x
        key.y = key.y - min_y
        # rotation is always expressed in relation to key center
        key.rotation_x = key.x + key.width / 2 if key.rotation_angle else 0
        key.rotation_y = key.y + key.height / 2 if key.rotation_angle else 0

    # and sort (topmost leftmost first)
    keys = sorted(keys, key=lambda k: [k.y, k.x])

    return Keyboard(meta=metadata, keys=keys)


def get_keyboard(layout: dict) -> Keyboard:
    try:
        return parse_kle(layout)
    except Exception:
        pass
    try:
        return parse_via(layout)
    except Exception:
        pass
    try:
        return parse_qmk(layout)
    except Exception:
        pass
    try:
        return Keyboard.from_json(layout)
    except Exception:
        pass
    try:
        return parse_ergogen_points(layout)
    except Exception:
        pass
    msg = "Unable to get keyboard layout"
    raise RuntimeError(msg)


def get_keyboard_from_file(layout_path: Union[str, os.PathLike]) -> Keyboard:
    # Layout downloaded from keyboard-layout-editor is most likely using utf-8.
    # Use it explicitly in case the platform locale sets different encoding.
    with open(layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)
    logger.info(f"User layout: {layout}")
    return get_keyboard(layout)


class KeyboardTag(Enum):
    ORTHOLINEAR = auto()
    ROW_STAGGERED = auto()
    COLUMN_STAGGERED = auto()
    OTHER = auto()
    ISO = auto()
    WITH_UNRECOGNIZED_KEY_SHAPE = auto()


def layout_classification(keyboard: Keyboard) -> List[KeyboardTag]:
    """Get the list of tags based on layout characteristics"""
    tags = []

    def is_standard_shape(key: Key) -> bool:
        if key.width2 == key.width and key.height2 == key.height:
            return True
        return False

    def is_iso_enter(key: Key) -> bool:
        if (
            key.width == 1.25
            and key.height == 2
            and key.width2 == 1.5
            and key.height2 == 1
        ):
            return True
        return False

    if isinstance(keyboard, MatrixAnnotatedKeyboard):
        keys = keyboard.keys_in_matrix_order()
    else:
        keys = keyboard.keys

    reference_key = keys[0]

    x_ortholinear_keys = 0
    y_ortholinear_keys = 0
    rotated_keys = 0
    encoders = 0
    iso_enters = 0
    unrecognized_shape_keys = 0

    for k in keys:
        if float(k.x - reference_key.x).is_integer():
            x_ortholinear_keys += 1
        if float(k.y - reference_key.y).is_integer():
            y_ortholinear_keys += 1
        if k.rotation_angle != 0:
            rotated_keys += 1
        if not is_standard_shape(k):
            if is_iso_enter(k):
                iso_enters += 1
            else:
                unrecognized_shape_keys += 1

    logger.debug(
        f"Layout with: {x_ortholinear_keys=}, {y_ortholinear_keys=}, {rotated_keys=}, "
        f"{encoders=}, {iso_enters=} and {unrecognized_shape_keys=}"
    )

    all_keys = len(keyboard.keys) - encoders
    if (
        x_ortholinear_keys == all_keys
        and y_ortholinear_keys == all_keys
        and rotated_keys == 0
    ):
        tags.append(KeyboardTag.ORTHOLINEAR)
    elif rotated_keys != 0:
        tags.append(KeyboardTag.OTHER)
    elif x_ortholinear_keys == all_keys:
        tags.append(KeyboardTag.COLUMN_STAGGERED)
    else:
        tags.append(KeyboardTag.ROW_STAGGERED)

    if iso_enters != 0:
        tags.append(KeyboardTag.ISO)

    if unrecognized_shape_keys != 0:
        tags.append(KeyboardTag.WITH_UNRECOGNIZED_KEY_SHAPE)

    logger.debug(f"Layout tagged: {tags}")
    return tags


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KLE format converter")
    parser.add_argument("-i", "--in", required=True, help="Layout file")
    parser.add_argument(
        "--inform",
        required=False,
        default="KLE_RAW",
        choices=["KLE_RAW", "KLE_VIA", "KLE_INTERNAL", "ERGOGEN_INTERNAL", "QMK"],
        help="Specifies the input format",
    )
    parser.add_argument("-o", "--out", required=False, help="Result file")
    parser.add_argument(
        "--outform",
        required=False,
        default="KLE_INTERNAL",
        choices=["KLE_RAW", "KLE_INTERNAL"],
        help="Specifies the output format",
    )
    parser.add_argument(
        "--text", required=False, action="store_true", help="Print result"
    )
    parser.add_argument(
        "--ergogen-filter",
        required=False,
        type=str,
        help="Ergogen zone filter regular expression, applicable only when -inform ERGOGEN_INTERNAL",
    )
    parser.add_argument(
        "--collapse",
        action="store_true",
        help=(
            "Collapse via-like annotated layout, "
            "applicable only when -inform equal KLE_RAW, KLE_VIA or KLE_INTERNAL"
        ),
    )

    args = parser.parse_args()
    input_path = getattr(args, "in")
    input_format = args.inform
    output_path = getattr(args, "out")
    output_format = args.outform
    print_result = args.text
    ergogen_filter = args.ergogen_filter
    collapse = args.collapse

    if input_format == output_format and not collapse:
        print("Output format equal input format, nothing to do...")
        sys.exit(1)

    def _keyboard_to_kle_raw(keyboard: Keyboard):
        result = keyboard.to_kle()
        if print_result:
            print(result)
        # 'to_kle' returns 'raw data' string which can be copy pasted
        # to keyboard-layout-editor, to make json out of it we need
        # to wrap it in list. Then it can be uploaded as JSON.
        result = "[" + result + "]"
        return json.loads(result)

    def _keyboard_to_kle_internal(keyboard: Keyboard):
        result = json.loads(keyboard.to_json())
        if print_result:
            pprint.pprint(result)
        return result

    with open(input_path, "r", encoding="utf-8") as input_file:
        if input_path.endswith("yaml") or input_path.endswith("yml"):
            try:
                import yaml

                layout = yaml.safe_load(input_file)
            except Exception as e:
                msg = (
                    "Could not load yaml file, make sure that `PyYAML` installed "
                    "and yaml file format correct"
                )
                raise RuntimeError(msg) from e
        else:
            layout = json.load(input_file)

        result = ""
        if input_format == "KLE_RAW":
            keyboard = parse_kle(layout)
        elif input_format == "KLE_VIA":
            # 'parse_via' creates MatrixAnnotatedKeyboard which is our
            # internal representation and it is not the same thing
            # as KLE_INTERNAL format, so it is not used here
            keyboard = parse_kle(layout["layouts"]["keymap"])
        elif input_format == "KLE_INTERNAL":
            keyboard = Keyboard.from_json(layout)
        elif input_format == "ERGOGEN_INTERNAL":
            keyboard = parse_ergogen_points(layout, zone_filter=ergogen_filter)
        else:  # QMK
            keyboard = parse_qmk(layout).to_keyboard()

        if collapse:
            keyboard = MatrixAnnotatedKeyboard(meta=keyboard.meta, keys=keyboard.keys)
            keyboard.collapse()
            keyboard = keyboard.to_keyboard()

        if output_format == "KLE_INTERNAL":
            result = _keyboard_to_kle_internal(keyboard)
        else:  # KLE_RAW
            result = _keyboard_to_kle_raw(keyboard)

        if output_path:
            with open(output_path, "w", encoding="utf-8") as output_file:
                json.dump(result, output_file, indent=2)
