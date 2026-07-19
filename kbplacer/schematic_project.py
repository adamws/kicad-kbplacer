# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .board_modifier import KICAD_VERSION
from .led_schematic_builder import create_led_chain_schematic
from .project_builder import create_project_file
from .schematic_builder import create_key_matrix_schematic

# Index 0 = highest-priority primary sheet. "mcu" is reserved for a future
# stage; requesting it today raises (see `_build_one`), it's listed here only
# so its priority slot is already carved out.
SHEET_TYPE_PRIORITY = ["mcu", "key_matrix", "led_chain"]

IMPLEMENTED_SHEET_TYPES = {"key_matrix", "led_chain"}

SHEET_FILE_SUFFIXES = {
    "mcu": "mcu",
    "key_matrix": "key-matrix",
    "led_chain": "led-chain",
}

SHEET_DISPLAY_NAMES = {
    "mcu": "MCU",
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
    requested_types: List[str],
    strategy: str = "flat",
) -> List[Tuple[str, str]]:
    """Return `(sheet_type, filename)` pairs in page order for `requested_types`.

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
    ordered_types = sorted(requested_types, key=SHEET_TYPE_PRIORITY.index)
    all_suffixed = strategy == "hierarchical" and len(ordered_types) > 1
    planned = []
    for index, sheet_type in enumerate(ordered_types):
        if index == 0 and not all_suffixed:
            filename = f"{project_basename}.kicad_sch"
        else:
            suffix = SHEET_FILE_SUFFIXES[sheet_type]
            filename = f"{project_basename}-{suffix}.kicad_sch"
        planned.append((sheet_type, filename))
    return planned


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
) -> None:
    if sheet_type == "key_matrix":
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


def create_schematic_project(
    project_path,
    layout_path,
    requests: List[SchematicRequest],
    *,
    strategy: Optional[str] = None,
) -> None:
    """Build a KiCad project bundling one `.kicad_sch` per requested type.

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

    resolved_strategy = resolve_bundle_strategy(strategy)

    if resolved_strategy == "flat" and len(requests) > 1 and KICAD_VERSION < (10, 0, 0):
        msg = (
            "Bundling multiple schematic sheets into one project requires "
            "KiCad 10.0 or higher"
        )
        raise RuntimeError(msg)

    project_path = Path(project_path)
    project_name = project_path.stem

    requests_by_type = {r.sheet_type: r for r in requests}
    planned_filenames = plan_sheet_filenames(
        project_name, list(requested_types), strategy=resolved_strategy
    )

    if resolved_strategy == "hierarchical" and len(requests) > 1:
        root_uuid = str(uuid.uuid4())
        root_filename = hierarchical_root_filename(project_name)

        children = []
        planned = []
        for page, (sheet_type, filename) in enumerate(planned_filenames, start=2):
            sheet_uuid = str(uuid.uuid4())
            display_name = SHEET_DISPLAY_NAMES[sheet_type]
            output_path = project_path.parent / filename

            children.append((sheet_uuid, filename, display_name, page))
            planned.append(
                (
                    requests_by_type[sheet_type],
                    output_path,
                    str(uuid.uuid4()),
                    page,
                    f"/{root_uuid}/{sheet_uuid}",
                )
            )

        for request, output_path, own_uuid, page, instance_path in planned:
            _build_one(
                request.sheet_type,
                layout_path,
                output_path,
                project_name=project_name,
                own_uuid=own_uuid,
                sheet_page=page,
                instance_path=instance_path,
                extra_kwargs=request.kwargs,
            )

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
        return

    sheets = []
    planned = []
    for page, (sheet_type, filename) in enumerate(planned_filenames, start=1):
        own_uuid = str(uuid.uuid4())
        display_name = SHEET_DISPLAY_NAMES[sheet_type]
        output_path = project_path.parent / filename

        sheets.append((own_uuid, filename, display_name))
        planned.append((requests_by_type[sheet_type], output_path, own_uuid, page))

    for request, output_path, own_uuid, page in planned:
        _build_one(
            request.sheet_type,
            layout_path,
            output_path,
            project_name=project_name,
            own_uuid=own_uuid,
            sheet_page=page,
            extra_kwargs=request.kwargs,
        )

    create_project_file(project_path, sheets=sheets)
