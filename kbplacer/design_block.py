# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layout independent keyboard circuits (presets) backed by KiCad design blocks.

A preset is a KiCad design block (a `<name>.kicad_block` directory holding a
`<name>.kicad_sch` and optionally a `<name>.kicad_pcb`), so it stays usable and
editable in KiCad without kbplacer. kbplacer adds it to a generated project as
one schematic sheet per preset and copies its PCB layout (footprints, tracks,
vias, zones and drawings) to the generated board.

Because several presets (and the generated key matrix) are combined in one
project, a preset instance is first *planned*:

- every reference is renumbered after the references used by the key matrix,
  the LED chain and previously planned presets (`C1` -> `C70`), consistently
  in the schematic sheet and on the board,
- global labels named `GPIO<n>` mark microcontroller pins which can drive the
  key matrix; they are renamed to the matrix nets (`ROW0`, ..., `COL0`, ...),
  rows first, then columns, in `GPIO` number order (or user given order).
  Unused `GPIO<n>` labels are left as they are.

All other global labels (for example `MCU_D+`) are kept: they are the way
presets connect to each other (e.g. microcontroller with USB connector).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple, Union

import pcbnew

from .board_modifier import KICAD_VERSION, duplicate_footprint
from .builders_commons import matrix_net_name
from .element_position import Side
from .kle_serial import MatrixAnnotatedKeyboard

logger = logging.getLogger(__name__)

DESIGN_BLOCK_SUFFIX = ".kicad_block"
DESIGN_BLOCK_LIBRARY_SUFFIX = ".kicad_blocks"

GPIO_LABEL_PATTERN = re.compile(r"^GPIO(\d+)$")

_REFERENCE_PATTERN = re.compile(r"^(#?[A-Za-z_]+)(\d+)$")
_AUTO_NET_PATTERN = re.compile(r"^(Net|unconnected)-\(([^-()]+)-(.*)\)$")

# Margin between the keyboard and presets parked below it (and between
# consecutive presets) when no explicit preset position is requested, in mm.
PRESET_PARKING_GAP = 5.0


@dataclass
class DesignBlock:
    name: str
    directory: Path
    schematic_path: Optional[Path]
    pcb_path: Optional[Path]
    description: str = ""

    @classmethod
    def from_identifier(cls, identifier: str) -> DesignBlock:
        """Resolve a design block from a path or a library identifier.

        Accepted forms:
        - `path/to/name.kicad_block` - a design block directory,
        - `path/to/library.kicad_blocks:name` - a block in a design block
          library, the same `library_path:item` convention which footprint
          identifiers use.
        """
        directory = Path(identifier)
        if not directory.is_dir():
            library, name = _split_library_identifier(identifier)
            directory = Path(library) / f"{name}{DESIGN_BLOCK_SUFFIX}"
            if not directory.is_dir():
                msg = f"Design block '{name}' not found in library '{library}'"
                raise ValueError(msg)

        if directory.suffix != DESIGN_BLOCK_SUFFIX:
            msg = f"'{directory}' is not a design block directory ('*.kicad_block')"
            raise ValueError(msg)

        name = directory.stem
        schematic_path = directory / f"{name}.kicad_sch"
        pcb_path = directory / f"{name}.kicad_pcb"
        metadata_path = directory / f"{name}.json"

        description = ""
        if metadata_path.is_file():
            with open(metadata_path, "r") as f:
                description = json.load(f).get("description", "")

        block = cls(
            name=name,
            directory=directory,
            schematic_path=schematic_path if schematic_path.is_file() else None,
            pcb_path=pcb_path if pcb_path.is_file() else None,
            description=description,
        )
        if not block.schematic_path and not block.pcb_path:
            msg = f"Design block '{directory}' has neither schematic nor PCB"
            raise ValueError(msg)
        return block


def _split_library_identifier(identifier: str) -> Tuple[str, str]:
    if len(identifier) >= 3 and identifier[1:3] == ":\\":
        # Windows path (C:\...), library/name separator is the second colon
        separator = identifier.find(":", 2)
    else:
        separator = identifier.find(":")
    if separator == -1:
        msg = (
            f"'{identifier}' is neither a design block directory nor "
            "a 'path/to/library.kicad_blocks:block_name' identifier"
        )
        raise ValueError(msg)
    library, name = identifier[:separator], identifier[separator + 1 :]
    if not library.endswith(DESIGN_BLOCK_LIBRARY_SUFFIX) or not name:
        msg = (
            f"'{identifier}' invalid design block identifier, expected "
            "'path/to/library.kicad_blocks:block_name'"
        )
        raise ValueError(msg)
    return library, name


@dataclass
class PresetSpec:
    """User request for a preset, `position` is `(x, y, rotation)` of the
    design block origin on the board (mm, mm, degrees), `None` to place it
    automatically below the keyboard. `side` is the board side of the block
    components, `None` keeps the side the block was designed with."""

    identifier: str
    position: Optional[Tuple[float, float, float]] = None
    side: Optional[Side] = None


@dataclass
class PresetInstance:
    block: DesignBlock
    sheet_name: str
    position: Optional[Tuple[float, float, float]]
    # non-power references, shared by the sheet and the board
    references: Dict[str, str]
    # GPIO<n> label/net name -> matrix net name
    nets: Dict[str, str]
    # namespace for deterministic re-generation of the block UUIDs, so that
    # the schematic sheet and the board agree on symbol UUIDs (footprint paths)
    uuid_seed: uuid.UUID = field(default_factory=uuid.uuid4)
    # board side of the block components, `None` keeps the block's own side
    side: Optional[Side] = None
    # KIID path of the generated sheet, as used in footprint paths, set when
    # the sheet is created (see `schematic_project.create_schematic_project`),
    # `None` when unknown - footprints are then linked by reference only
    sheet_path: Optional[str] = None

    def new_uuid(self, old: str) -> str:
        return str(uuid.uuid5(self.uuid_seed, old))

    def pcb_net_name(self, name: str) -> str:
        """Name of a block PCB net after placing the block in a project."""
        if not name:
            return name
        if name in self.nets:
            return self.nets[name]
        match = _AUTO_NET_PATTERN.match(name)
        if match:
            # KiCad's auto-generated names embed the reference of a pin
            kind, reference, rest = match.groups()
            reference = self.references.get(reference, reference)
            return f"{kind}-({reference}-{rest})"
        if name.startswith("/"):
            # local net of the block's root sheet becomes local to preset sheet
            return f"/{self.sheet_name}{name}"
        return name


@dataclass
class _BlockContent:
    references: List[str]
    gpio_labels: List[str]


def _read_schematic_references(text: str) -> List[str]:
    """References of placed symbols (from their instance data).

    Symbols may keep stale instance data of other projects they were copied
    from, only the first entry of each symbol counts, matching what
    `write_preset_schematic` keeps.
    """
    references = []
    for match in re.finditer(r"\(instances\b", text):
        block = text[match.start() : _sexpr_end(text, match.start())]
        reference = re.search(r'\(reference "([^"]+)"\)', block)
        if reference:
            references.append(reference.group(1))
    return references


def _read_block_content(block: DesignBlock) -> _BlockContent:
    references: List[str] = []
    gpio_labels: Set[str] = set()
    if block.schematic_path:
        text = block.schematic_path.read_text()
        references.extend(_read_schematic_references(text))
        for label in re.findall(r'\(global_label "([^"]+)"', text):
            if GPIO_LABEL_PATTERN.match(label):
                gpio_labels.add(label)
    if block.pcb_path:
        text = block.pcb_path.read_text()
        footprint_references = re.findall(
            r'\(property "Reference" "([^"]+)"', text
        ) + re.findall(r'\(fp_text reference "([^"]+)"', text)
        references.extend(footprint_references)
        if not block.schematic_path:
            nets = re.findall(r'\(net (?:\d+ )?"([^"]+)"\)', text)
            gpio_labels.update(n for n in nets if GPIO_LABEL_PATTERN.match(n))
    # keep first-seen order, de-duplicated (multi-unit symbols share reference)
    unique_references = list(dict.fromkeys(references))
    return _BlockContent(
        references=unique_references,
        gpio_labels=sorted(
            gpio_labels, key=lambda n: int(GPIO_LABEL_PATTERN.match(n).group(1))
        ),
    )


def split_reference(reference: str) -> Optional[Tuple[str, int]]:
    match = _REFERENCE_PATTERN.match(reference)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def allocate_references(
    references: Iterable[str], taken: Dict[str, int], *, block_name: str = ""
) -> Dict[str, str]:
    """Renumber `references` after the highest number already `taken` for
    each prefix, keeping their relative order. Updates `taken` in place so
    successive calls never collide.
    """
    by_prefix: Dict[str, List[Tuple[int, str]]] = {}
    for reference in references:
        parts = split_reference(reference)
        if parts is None:
            if reference.endswith("?") or reference == "REF**":
                msg = (
                    f"Design block '{block_name}' contains unannotated "
                    f"reference '{reference}', annotate it in KiCad first"
                )
                raise ValueError(msg)
            logger.warning(f"Keeping unrecognized reference '{reference}' as is")
            continue
        prefix, number = parts
        by_prefix.setdefault(prefix, []).append((number, reference))

    mapping: Dict[str, str] = {}
    for prefix, items in by_prefix.items():
        next_number = taken.get(prefix, 0) + 1
        for _, reference in sorted(items):
            mapping[reference] = f"{prefix}{next_number}"
            taken[prefix] = next_number
            next_number += 1
    return mapping


def _unique_matrix_positions(
    keyboard: MatrixAnnotatedKeyboard,
) -> List[Tuple[str, str]]:
    keys = keyboard.keys_in_matrix_order()
    positions = [MatrixAnnotatedKeyboard.get_matrix_position(k) for k in keys]
    return list(dict.fromkeys(positions))


def _natural_key(value: str) -> List[Union[int, str]]:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", value)]


def matrix_net_names(keyboard: MatrixAnnotatedKeyboard) -> List[str]:
    """Row nets followed by column nets, both naturally sorted, named exactly
    like the board builder and key matrix schematic name them."""
    positions = _unique_matrix_positions(keyboard)
    rows = {matrix_net_name("ROW", row) for row, _ in positions}
    columns = {matrix_net_name("COL", column) for _, column in positions}
    return sorted(rows, key=_natural_key) + sorted(columns, key=_natural_key)


def reserved_references(
    keyboard: MatrixAnnotatedKeyboard,
    *,
    start_index: int = 1,
    with_leds: bool = False,
    with_led_capacitors: bool = False,
) -> Dict[str, int]:
    """Highest reference number used by generated (layout dependent) parts,
    per prefix. Computed from the layout rather than read back from generated
    files so that the schematic and the board always agree, regardless of
    which of them are generated in a given run."""
    if start_index < 0:
        start_index = 1
    count = len(_unique_matrix_positions(keyboard))
    if count == 0:
        return {}
    last = start_index + count - 1
    prefixes = ["SW", "D", "ST"]
    if with_leds:
        prefixes.append("LED")
        if with_led_capacitors:
            prefixes.append("C")
    return {prefix: last for prefix in prefixes}


def _unique_sheet_name(name: str, used: Set[str]) -> str:
    candidate = name
    index = 2
    while candidate in used:
        candidate = f"{name}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def plan_presets(
    specs: List[PresetSpec],
    keyboard: MatrixAnnotatedKeyboard,
    *,
    start_index: int = 1,
    with_leds: bool = False,
    with_led_capacitors: bool = False,
    matrix_pin_order: Optional[List[str]] = None,
) -> List[PresetInstance]:
    """Resolve requested presets and plan their reference and net renames."""
    if not specs:
        return []

    taken = reserved_references(
        keyboard,
        start_index=start_index,
        with_leds=with_leds,
        with_led_capacitors=with_led_capacitors,
    )
    sheet_names: Set[str] = set()
    blocks = [DesignBlock.from_identifier(spec.identifier) for spec in specs]
    contents = [_read_block_content(block) for block in blocks]

    controllers = [i for i, content in enumerate(contents) if content.gpio_labels]
    if len(controllers) > 1:
        names = ", ".join(blocks[i].name for i in controllers)
        msg = (
            f"Only one preset may expose GPIO labels for the key matrix, "
            f"found: {names}"
        )
        raise ValueError(msg)

    instances: List[PresetInstance] = []
    for spec, block, content in zip(specs, blocks, contents):
        references = allocate_references(
            [r for r in content.references if not r.startswith("#")],
            taken,
            block_name=block.name,
        )
        nets: Dict[str, str] = {}
        if content.gpio_labels:
            nets = _assign_matrix_nets(
                block, content.gpio_labels, keyboard, matrix_pin_order
            )
        instance = PresetInstance(
            block=block,
            sheet_name=_unique_sheet_name(block.name, sheet_names),
            position=spec.position,
            side=spec.side,
            references=references,
            nets=nets,
        )
        logger.info(
            f"Preset {instance.sheet_name}: references {references}, nets {nets}"
        )
        instances.append(instance)

    if not controllers:
        logger.warning(
            "None of the presets exposes GPIO labels, "
            "key matrix is not connected to any of them"
        )
    if matrix_pin_order and not controllers:
        msg = "Matrix pin order given but no preset exposes GPIO labels"
        raise ValueError(msg)
    return instances


def _assign_matrix_nets(
    block: DesignBlock,
    gpio_labels: List[str],
    keyboard: MatrixAnnotatedKeyboard,
    matrix_pin_order: Optional[List[str]],
) -> Dict[str, str]:
    order = gpio_labels
    if matrix_pin_order:
        unknown = [p for p in matrix_pin_order if p not in gpio_labels]
        if unknown:
            msg = (
                f"Matrix pin order refers to labels not present in design "
                f"block '{block.name}': {unknown}, available: {gpio_labels}"
            )
            raise ValueError(msg)
        if len(set(matrix_pin_order)) != len(matrix_pin_order):
            msg = "Matrix pin order contains duplicates"
            raise ValueError(msg)
        order = matrix_pin_order

    matrix_nets = matrix_net_names(keyboard)
    if len(matrix_nets) > len(order):
        msg = (
            f"Key matrix needs {len(matrix_nets)} pins ({', '.join(matrix_nets)}) "
            f"but design block '{block.name}' provides only {len(order)}"
        )
        raise ValueError(msg)
    return dict(zip(order, matrix_nets))


def _sexpr_end(text: str, start: int) -> int:
    """Index just past the s-expression opened at `text[start]`.
    KiCad strings may contain parentheses, so quoted strings are skipped."""
    depth = 0
    in_string = False
    i = start
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    msg = "Unbalanced s-expression"
    raise ValueError(msg)


def _replace_blocks(text: str, pattern: str, replace: Callable[[str], str]) -> str:
    """Replace every s-expression starting with `pattern` by `replace(block)`."""
    out = []
    position = 0
    for match in re.finditer(pattern, text):
        if match.start() < position:
            continue  # nested in an already replaced block
        end = _sexpr_end(text, match.start())
        out.append(text[position : match.start()])
        out.append(replace(text[match.start() : end]))
        position = end
    out.append(text[position:])
    return "".join(out)


def used_power_references(paths: Iterable[Path]) -> Dict[str, int]:
    """Highest power symbol (`#PWR`, `#FLG`, ...) reference numbers used in
    already generated schematic files."""
    taken: Dict[str, int] = {}
    for path in paths:
        for reference in _read_schematic_references(Path(path).read_text()):
            parts = split_reference(reference)
            if parts and parts[0].startswith("#"):
                taken[parts[0]] = max(taken.get(parts[0], 0), parts[1])
    return taken


def write_preset_schematic(
    instance: PresetInstance,
    output_path: Union[str, Path],
    *,
    project_name: str,
    own_uuid: str,
    sheet_page: int = 1,
    instance_path: Optional[str] = None,
    power_references: Optional[Dict[str, int]] = None,
) -> None:
    """Write design block schematic as a sheet of `project_name` project.

    `instance_path` semantics follow the other sheet builders: `None` for a
    top-level (flat or single) sheet, `/<root_uuid>/<sheet_uuid>` for a child
    of the hierarchical root. `power_references` are power symbol numbers
    already used by other sheets (updated in place).
    """
    block = instance.block
    if not block.schematic_path:
        msg = f"Design block '{block.name}' has no schematic"
        raise ValueError(msg)
    text = block.schematic_path.read_text()

    if re.search(r"\n\s*\(sheet\s*\n", text):
        msg = (
            f"Design block '{block.name}' contains hierarchical sheets, "
            "which are not supported yet"
        )
        raise NotImplementedError(msg)

    references = dict(instance.references)
    power = [r for r in _read_schematic_references(text) if r.startswith("#")]
    references.update(
        allocate_references(
            dict.fromkeys(power),
            power_references if power_references is not None else {},
            block_name=block.name,
        )
    )

    root_match = re.search(r'\(uuid "([^"]+)"\)', text)
    if not root_match:
        msg = f"Design block '{block.name}' schematic has no UUID"
        raise ValueError(msg)
    root_uuid = root_match.group(1)

    def _uuid(match: re.Match) -> str:
        old = match.group(1)
        new = own_uuid if old == root_uuid else instance.new_uuid(old)
        return f'(uuid "{new}")'

    text = re.sub(r'\(uuid "([^"]+)"\)', _uuid, text)

    resolved_instance_path = instance_path or f"/{own_uuid}"

    def _instances(block_text: str) -> str:
        match = re.search(r'\(reference "([^"]+)"\)\s*\(unit (\d+)\)', block_text)
        if not match:
            msg = f"Unexpected symbol instance data in '{block.name}'"
            raise ValueError(msg)
        reference = references.get(match.group(1), match.group(1))
        return (
            f'(instances (project "{project_name}" '
            f'(path "{resolved_instance_path}" '
            f'(reference "{reference}") (unit {match.group(2)}))))'
        )

    text = _replace_blocks(text, r"\(instances\b", _instances)

    def _reference_property(match: re.Match) -> str:
        reference = references.get(match.group(1), match.group(1))
        return f'(property "Reference" "{reference}"'

    text = re.sub(r'\(property "Reference" "([^"]+)"', _reference_property, text)

    def _global_label(match: re.Match) -> str:
        return f'(global_label "{instance.nets.get(match.group(1), match.group(1))}"'

    text = re.sub(r'\(global_label "([^"]+)"', _global_label, text)

    if instance_path is None:
        sheet_instances = f'(sheet_instances (path "/" (page "{sheet_page}")))'
    else:
        # children of hierarchical root do not carry their own sheet instances
        sheet_instances = ""
    if "(sheet_instances" in text:
        text = _replace_blocks(text, r"\(sheet_instances\b", lambda _: sheet_instances)
    else:
        closing = text.rstrip().rfind(")")
        text = f"{text[:closing]}\t{sheet_instances}\n)\n"

    with open(output_path, "w") as f:
        f.write(text)


def _duplicate(item: pcbnew.BOARD_ITEM) -> pcbnew.BOARD_ITEM:
    if isinstance(item, pcbnew.FOOTPRINT):
        return duplicate_footprint(item)
    if KICAD_VERSION >= (10, 0, 0):
        try:
            duplicate = item.Duplicate(False)
        except TypeError:
            duplicate = item.Duplicate()
    else:
        duplicate = item.Duplicate()
    return duplicate.Cast() if type(duplicate) is pcbnew.BOARD_ITEM else duplicate


def _get_or_add_net(board: pcbnew.BOARD, name: str) -> pcbnew.NETINFO_ITEM:
    net = board.FindNet(name)
    if net is None:
        net = pcbnew.NETINFO_ITEM(board, name, -1)
        if KICAD_VERSION < (8, 0, 0):
            board.GetNetInfo().AppendNet(net)
        board.Add(net)
    return net


def _bounding_box(items: Iterable[pcbnew.BOARD_ITEM]) -> Optional[pcbnew.BOX2I]:
    box = None
    for item in items:
        if isinstance(item, pcbnew.FOOTPRINT):
            item_box = item.GetBoundingBox(False, False)
        else:
            item_box = item.GetBoundingBox()
        if box is None:
            box = pcbnew.BOX2I(item_box.GetOrigin(), item_box.GetSize())
        else:
            box.Merge(item_box)
    return box


def _footprints_bounding_box(board: pcbnew.BOARD) -> Optional[pcbnew.BOX2I]:
    return _bounding_box(board.GetFootprints())


def block_side(board: pcbnew.BOARD) -> Side:
    """Side of the board most of the footprints are on."""
    sides = [f.IsFlipped() for f in board.GetFootprints()]
    return Side.BACK if sum(sides) > len(sides) / 2 else Side.FRONT


def _flip(item: pcbnew.BOARD_ITEM, centre: pcbnew.VECTOR2I) -> None:
    """Mirror item to the other board side, left to right around `centre`
    (KiCad's default flip direction)."""
    if KICAD_VERSION >= (9, 0, 0):
        item.Flip(centre, pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    else:
        item.Flip(centre, True)


class PresetBoardPlacer:
    """Adds planned presets to a board, by default parking them in a row
    below the footprints which are already on the board (i.e. the keyboard).
    """

    def __init__(self, board: pcbnew.BOARD) -> None:
        self.board = board
        keyboard_box = _footprints_bounding_box(board)
        if keyboard_box:
            self._next_x = keyboard_box.GetLeft()
            self._parking_y = keyboard_box.GetBottom() + pcbnew.FromMM(
                PRESET_PARKING_GAP
            )
        else:
            self._next_x = 0
            self._parking_y = 0

    def add(self, instance: PresetInstance) -> Optional[pcbnew.PCB_GROUP]:
        """Copy `instance`'s PCB layout to the board, returns the group which
        holds the copied items. Footprints are linked to symbols of the
        generated sheet if its `sheet_path` is known, otherwise by reference
        only, like the generated key matrix footprints."""
        block = instance.block
        if not block.pcb_path:
            logger.warning(f"Design block '{block.name}' has no PCB, skipping")
            return None

        source = pcbnew.LoadBoard(str(block.pcb_path))
        items = list(source.GetFootprints())
        items += list(source.GetTracks())
        items += list(source.Zones())
        items += list(source.GetDrawings())
        if not items:
            return None

        group = pcbnew.PCB_GROUP(self.board)
        group.SetName(instance.sheet_name)
        self.board.Add(group)

        copies = []
        for item in items:
            copy = _duplicate(item)
            self.board.Add(copy)
            if isinstance(copy, pcbnew.FOOTPRINT):
                self._relink_footprint(instance, item, copy)
            elif isinstance(copy, pcbnew.BOARD_CONNECTED_ITEM):
                self._set_net(instance, copy, item.GetNetname())
            group.AddItem(copy)
            copies.append(copy)

        if instance.side and instance.side != block_side(source):
            # around block origin, so that `position` keeps its meaning
            origin = pcbnew.VECTOR2I(0, 0)
            for copy in copies:
                _flip(copy, origin)
        self._move(instance, copies)
        return group

    def _set_net(
        self, instance: PresetInstance, item: pcbnew.BOARD_CONNECTED_ITEM, name: str
    ) -> None:
        name = instance.pcb_net_name(name)
        if name:
            item.SetNet(_get_or_add_net(self.board, name))
        else:
            item.SetNetCode(0)

    def _relink_footprint(
        self,
        instance: PresetInstance,
        source: pcbnew.FOOTPRINT,
        footprint: pcbnew.FOOTPRINT,
    ) -> None:
        reference = source.GetReference()
        footprint.SetReference(instance.references.get(reference, reference))

        for source_pad, pad in zip(source.Pads(), footprint.Pads()):
            self._set_net(instance, pad, source_pad.GetNetname())

        symbol_path = source.GetPath().AsString()
        if instance.sheet_path is not None and symbol_path:
            symbol_uuid = instance.new_uuid(symbol_path.split("/")[-1])
            path = f"{instance.sheet_path}/{symbol_uuid}"
            footprint.SetPath(pcbnew.KIID_PATH(path))
        else:
            footprint.SetPath(pcbnew.KIID_PATH())
        # block's own sheet details are meaningless in the target project,
        # KiCad fills them in on "Update PCB from Schematic"
        footprint.SetSheetname("")
        footprint.SetSheetfile("")

    def _move(
        self,
        instance: PresetInstance,
        items: List[pcbnew.BOARD_ITEM],
    ) -> None:
        origin = pcbnew.VECTOR2I(0, 0)
        if instance.position:
            x, y, rotation = instance.position
            if rotation:
                angle = pcbnew.EDA_ANGLE(rotation, pcbnew.DEGREES_T)
                for item in items:
                    item.Rotate(origin, angle)
            offset = pcbnew.VECTOR2I_MM(x, y)
        else:
            # park block's bounding box top-left corner at next free slot
            box = _bounding_box(items)
            offset = pcbnew.VECTOR2I(
                self._next_x - box.GetLeft(), self._parking_y - box.GetTop()
            )
            self._next_x += box.GetWidth() + pcbnew.FromMM(PRESET_PARKING_GAP)
        for item in items:
            item.Move(offset)
