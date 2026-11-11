# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .board_modifier import KICAD_VERSION
from .design_block import used_power_references, write_preset_schematic
from .led_schematic_builder import create_led_chain_schematic
from .project_builder import create_project_file
from .schematic_builder import create_key_matrix_schematic

# Index 0 = highest-priority primary sheet. Presets (design blocks, see
# `design_block.py`) come last, so adding them never renames the generated
# key matrix/LED chain files. Unlike the other types, "preset" may be
# requested many times, each request distinguished by its `name`.
SHEET_TYPE_PRIORITY = ["key_matrix", "led_chain", "preset"]

IMPLEMENTED_SHEET_TYPES = {"key_matrix", "led_chain", "preset"}

SHEET_FILE_SUFFIXES = {
    "key_matrix": "key-matrix",
    "led_chain": "led-chain",
}

SHEET_DISPLAY_NAMES = {
    "key_matrix": "Key Matrix",
    "led_chain": "Led Chain",
}

BUNDLE_STRATEGIES = ("flat", "hierarchical")

HIERARCHICAL_ROOT_DISPLAY_NAME = "Root"

# Hierarchical root schematics carry no symbols/lib_symbols of their own -
# just `(sheet ...)` references - so they can always target the lower-common-
# denominator KiCad 9 file format, regardless of what version any individual
# child sheet requires.
_ROOT_TEMPLATE_HEADER = """\
(kicad_sch
    (version 20250114)
    (generator "eeschema")
    (generator_version "9.0")
    (uuid "{root_uuid}")
    (paper "A4")
    (lib_symbols)
"""

_ROOT_SHEET_BLOCK = """\
    (sheet
        (at {x} {y})
        (size {width} {height})
        (exclude_from_sim no)
        (in_bom yes)
        (on_board yes)
        (dnp no)
        (fields_autoplaced yes)
        (stroke
            (width 0.1524)
            (type solid)
        )
        (fill
            (color 0 0 0 0)
        )
        (uuid "{sheet_uuid}")
        (property "Sheetname" "{display_name}"
            (at {x} {sheetname_y} 0)
            (show_name no)
            (do_not_autoplace no)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (justify left bottom)
            )
        )
        (property "Sheetfile" "{filename}"
            (at {x} {sheetfile_y} 0)
            (show_name no)
            (do_not_autoplace no)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (justify left top)
            )
        )
        (instances
            (project "{project_name}"
                (path "/{root_uuid}"
                    (page "{page}")
                )
            )
        )
    )
"""

_ROOT_TEMPLATE_FOOTER = """\
    (sheet_instances
        (path "/"
            (page "1")
        )
    )
    (embedded_fonts no)
)
"""

# Sheet-symbol box size and grid layout (single column, stacked vertically),
# matching the proportions of a KiCad-drawn hierarchical sheet.
_ROOT_SHEET_SIZE = (23.495, 12.065)
_ROOT_SHEET_X = 21.59
_ROOT_SHEET_Y_START = 20.32
_ROOT_SHEET_ROW_PITCH = 20.0
_ROOT_SHEETNAME_Y_OFFSET = -0.7116
_ROOT_SHEETFILE_Y_OFFSET = 0.5846


@dataclass
class SchematicRequest:
    sheet_type: str
    kwargs: Dict[str, Any] = field(default_factory=dict)
    # distinguishes sheets of the same type (presets), used as the file
    # suffix and sheet name instead of the per-type defaults
    name: Optional[str] = None

    def __post_init__(self) -> None:
        if self.sheet_type == "preset" and not self.name:
            msg = "Preset schematic request requires a name"
            raise ValueError(msg)

    @property
    def key(self) -> str:
        return (
            self.sheet_type if self.name is None else f"{self.sheet_type}:{self.name}"
        )

    @property
    def file_suffix(self) -> str:
        return self.name if self.name else SHEET_FILE_SUFFIXES[self.sheet_type]

    @property
    def display_name(self) -> str:
        return self.name if self.name else SHEET_DISPLAY_NAMES[self.sheet_type]


RequestLike = Union[str, SchematicRequest]


def _as_requests(requested: List[RequestLike]) -> List[SchematicRequest]:
    return [
        r if isinstance(r, SchematicRequest) else SchematicRequest(r) for r in requested
    ]


def resolve_bundle_strategy(strategy: Optional[str]) -> str:
    """Resolve a user-supplied (or `None`) bundling strategy to a concrete one.

    `None` auto-selects: "flat" on KiCad 10+ (today's behavior, unchanged),
    "hierarchical" below that (instead of `create_schematic_project` erroring
    out on multi-sheet requests, as it did before hierarchical bundling
    existed). An explicit value is validated and returned as-is.
    """
    if strategy is None:
        return "flat" if KICAD_VERSION >= (10, 0, 0) else "hierarchical"
    if strategy not in BUNDLE_STRATEGIES:
        msg = (
            f"Unknown bundle strategy: {strategy!r}, "
            f"expected one of {BUNDLE_STRATEGIES}"
        )
        raise ValueError(msg)
    return strategy


def hierarchical_root_filename(project_basename: str) -> str:
    """Filename of the hierarchical-strategy root sheet for a given project."""
    return f"{project_basename}.kicad_sch"


def plan_sheet_filenames(
    project_basename: str,
    requested: List[RequestLike],
    strategy: str = "flat",
) -> List[Tuple[str, str]]:
    """Return `(key, filename)` pairs in page order for `requested` sheets.

    `requested` items are sheet types or `SchematicRequest`s, `key` is the
    sheet type, or `"<type>:<name>"` for named requests (see
    `SchematicRequest.key`).

    Exposed so callers (e.g. the CLI's pre-flight "already exists" check) can
    learn the exact output filenames `create_schematic_project` will use,
    without duplicating the priority-ordering/naming-convention logic.

    Under "flat" (or "hierarchical" with a single requested type, where no
    root wrapper is created), the highest-priority type gets the project-
    basename-matching filename and the rest get suffixed filenames. Under
    "hierarchical" with more than one requested type, every type gets a
    suffixed filename - none of them is the project's root sheet, since that
    role is filled by the wrapper root file (see `hierarchical_root_filename`).
    """
    ordered = _order_requests(_as_requests(requested))
    all_suffixed = strategy == "hierarchical" and len(ordered) > 1
    planned = []
    for index, request in enumerate(ordered):
        if index == 0 and not all_suffixed:
            filename = f"{project_basename}.kicad_sch"
        else:
            filename = f"{project_basename}-{request.file_suffix}.kicad_sch"
        planned.append((request.key, filename))
    return planned


def _order_requests(requests: List[SchematicRequest]) -> List[SchematicRequest]:
    # stable: named requests of one type keep the order they were given in
    return sorted(requests, key=lambda r: SHEET_TYPE_PRIORITY.index(r.sheet_type))


def _build_one(
    sheet_type: str,
    layout_path,
    output_path,
    *,
    project_name: str,
    own_uuid: str,
    sheet_page: int,
    instance_path: Optional[str] = None,
    extra_kwargs: Dict[str, Any],
    power_references: Optional[Dict[str, int]] = None,
) -> None:
    if sheet_type == "preset":
        write_preset_schematic(
            extra_kwargs["instance"],
            output_path,
            project_name=project_name,
            own_uuid=own_uuid,
            sheet_page=sheet_page,
            instance_path=instance_path,
            power_references=power_references,
        )
    elif sheet_type == "key_matrix":
        create_key_matrix_schematic(
            layout_path,
            output_path,
            project_name=project_name,
            own_uuid=own_uuid,
            sheet_page=sheet_page,
            instance_path=instance_path,
            **extra_kwargs,
        )
    elif sheet_type == "led_chain":
        create_led_chain_schematic(
            layout_path,
            output_path,
            project_name=project_name,
            own_uuid=own_uuid,
            sheet_page=sheet_page,
            instance_path=instance_path,
            **extra_kwargs,
        )
    else:
        msg = f"Schematic type not implemented yet: {sheet_type}"
        raise NotImplementedError(msg)


def _build_hierarchical_root(
    output_path,
    *,
    project_name: str,
    own_uuid: str,
    children: List[Tuple[str, str, str, int]],
) -> None:
    """Write the hierarchical-strategy root `.kicad_sch`.

    `children` is `(sheet_uuid, filename, display_name, page)` tuples, in page
    order (pages starting at 2 - the root itself is always page 1). Each
    becomes a `(sheet ...)` block referencing the child file; the root carries
    no symbols of its own.
    """
    width, height = _ROOT_SHEET_SIZE
    parts = [_ROOT_TEMPLATE_HEADER.format(root_uuid=own_uuid)]
    for index, (sheet_uuid, filename, display_name, page) in enumerate(children):
        x = _ROOT_SHEET_X
        y = _ROOT_SHEET_Y_START + index * _ROOT_SHEET_ROW_PITCH
        parts.append(
            _ROOT_SHEET_BLOCK.format(
                x=x,
                y=y,
                width=width,
                height=height,
                sheet_uuid=sheet_uuid,
                display_name=display_name,
                sheetname_y=y + _ROOT_SHEETNAME_Y_OFFSET,
                filename=filename,
                sheetfile_y=y + height + _ROOT_SHEETFILE_Y_OFFSET,
                project_name=project_name,
                root_uuid=own_uuid,
                page=page,
            )
        )
    parts.append(_ROOT_TEMPLATE_FOOTER)
    with open(output_path, "w") as f:
        f.write("".join(parts))


def _build_all(
    planned: List[Tuple[SchematicRequest, Path, str, int, Optional[str]]],
    layout_path,
    project_name: str,
) -> None:
    built: List[Path] = []
    power_references: Optional[Dict[str, int]] = None
    for request, output_path, own_uuid, page, instance_path in planned:
        if request.sheet_type == "preset" and power_references is None:
            # presets are ordered last, every other sheet is already written
            power_references = used_power_references(built)
        _build_one(
            request.sheet_type,
            layout_path,
            output_path,
            project_name=project_name,
            own_uuid=own_uuid,
            sheet_page=page,
            instance_path=instance_path,
            extra_kwargs=request.kwargs,
            power_references=power_references,
        )
        built.append(output_path)


def create_schematic_project(
    project_path,
    layout_path,
    requests: List[SchematicRequest],
    *,
    strategy: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Build a KiCad project bundling one `.kicad_sch` per request.

    `strategy` selects how multiple sheets are tied together:
    - "flat": every requested type becomes its own top-level sheet (KiCad 10's
      flat "top-level sheets" project feature), linked together purely through
      the written `.kicad_pro`. Requires KiCad 10.0+ whenever more than one
      sheet is requested.
    - "hierarchical": a root `.kicad_sch` containing a `(sheet ...)` reference
      to each requested type, in the traditional KiCad hierarchical-sheet
      style. Works on KiCad 9+. With only one requested type there is nothing
      to bundle, so no root wrapper is created either way - both strategies
      produce the same single, self-rooted sheet.

    `None` (the default) auto-selects a strategy from the running KiCad
    version - see `resolve_bundle_strategy`.

    Under either strategy, the highest-priority requested type
    (`SHEET_TYPE_PRIORITY`) determines page ordering; under "flat" (or a
    single-type request) it also gets the project-basename-matching filename
    and page 1, purely a naming/ordering convention since the file format
    itself treats every sheet as a peer. Under "hierarchical" with multiple
    types, the root wrapper takes the project-basename filename and page 1
    instead, and every requested type gets a suffixed filename (see
    `plan_sheet_filenames`).

    Returns, for each request `key`, the KIID path of its sheet as used in
    footprint paths of a board (`/<sheet_uuid>` for a hierarchical child, `""`
    for a single self-rooted sheet), or `None` where it can't be relied on:
    flat multi-sheet projects, whose top-level sheets KiCad's command line
    tools don't load, so footprint paths could not be verified.
    """
    if not requests:
        msg = "At least one schematic type must be requested"
        raise ValueError(msg)

    requested_types = {r.sheet_type for r in requests}
    unknown = requested_types - set(SHEET_TYPE_PRIORITY)
    if unknown:
        msg = f"Unknown schematic type(s): {sorted(unknown)}"
        raise ValueError(msg)

    unimplemented = requested_types - IMPLEMENTED_SHEET_TYPES
    if unimplemented:
        msg = f"Schematic type(s) not implemented yet: {sorted(unimplemented)}"
        raise NotImplementedError(msg)

    requests_by_key = {r.key: r for r in requests}
    if len(requests_by_key) != len(requests):
        msg = "Each schematic request must be unique (by type and name)"
        raise ValueError(msg)

    resolved_strategy = resolve_bundle_strategy(strategy)

    if resolved_strategy == "flat" and len(requests) > 1 and KICAD_VERSION < (10, 0, 0):
        msg = (
            "Bundling multiple schematic sheets into one project requires "
            "KiCad 10.0 or higher"
        )
        raise RuntimeError(msg)

    project_path = Path(project_path)
    project_name = project_path.stem

    planned_filenames = plan_sheet_filenames(
        project_name, list(requests), strategy=resolved_strategy
    )

    if resolved_strategy == "hierarchical" and len(requests) > 1:
        root_uuid = str(uuid.uuid4())
        root_filename = hierarchical_root_filename(project_name)

        children = []
        planned = []
        sheet_paths: Dict[str, Optional[str]] = {}
        for page, (key, filename) in enumerate(planned_filenames, start=2):
            request = requests_by_key[key]
            sheet_uuid = str(uuid.uuid4())
            output_path = project_path.parent / filename

            children.append((sheet_uuid, filename, request.display_name, page))
            planned.append(
                (
                    request,
                    output_path,
                    str(uuid.uuid4()),
                    page,
                    f"/{root_uuid}/{sheet_uuid}",
                )
            )
            sheet_paths[key] = f"/{sheet_uuid}"

        _build_all(planned, layout_path, project_name)

        _build_hierarchical_root(
            project_path.parent / root_filename,
            project_name=project_name,
            own_uuid=root_uuid,
            children=children,
        )

        root_sheet = (root_uuid, root_filename, HIERARCHICAL_ROOT_DISPLAY_NAME)
        sheets = [root_sheet] + [
            (sheet_uuid, filename, display_name)
            for sheet_uuid, filename, display_name, _page in children
        ]
        create_project_file(
            project_path,
            sheets=sheets,
            top_level_sheets=[root_sheet],
        )
        return sheet_paths

    sheets = []
    planned = []
    for page, (key, filename) in enumerate(planned_filenames, start=1):
        request = requests_by_key[key]
        own_uuid = str(uuid.uuid4())
        output_path = project_path.parent / filename

        sheets.append((own_uuid, filename, request.display_name))
        planned.append((request, output_path, own_uuid, page, None))

    _build_all(planned, layout_path, project_name)

    create_project_file(project_path, sheets=sheets)
    single_sheet_path = "" if len(requests) == 1 else None
    return {key: single_sheet_path for key, _ in planned_filenames}
