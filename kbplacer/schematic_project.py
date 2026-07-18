# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

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


@dataclass
class SchematicRequest:
    sheet_type: str
    kwargs: Dict[str, Any] = field(default_factory=dict)


def plan_sheet_filenames(
    project_basename: str, requested_types: List[str]
) -> List[Tuple[str, str]]:
    """Return `(sheet_type, filename)` pairs in page order for `requested_types`.

    Exposed so callers (e.g. the CLI's pre-flight "already exists" check) can
    learn the exact output filenames `create_schematic_project` will use,
    without duplicating the priority-ordering/naming-convention logic.
    """
    ordered_types = sorted(requested_types, key=SHEET_TYPE_PRIORITY.index)
    planned = []
    for index, sheet_type in enumerate(ordered_types):
        if index == 0:
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
    extra_kwargs: Dict[str, Any],
) -> None:
    if sheet_type == "key_matrix":
        create_key_matrix_schematic(
            layout_path,
            output_path,
            project_name=project_name,
            own_uuid=own_uuid,
            sheet_page=sheet_page,
            **extra_kwargs,
        )
    elif sheet_type == "led_chain":
        create_led_chain_schematic(
            layout_path,
            output_path,
            project_name=project_name,
            own_uuid=own_uuid,
            sheet_page=sheet_page,
            **extra_kwargs,
        )
    else:
        msg = f"Schematic type not implemented yet: {sheet_type}"
        raise NotImplementedError(msg)


def create_schematic_project(
    project_path,
    layout_path,
    requests: List[SchematicRequest],
) -> None:
    """Build a KiCad project bundling one `.kicad_sch` per requested type.

    Every requested type becomes its own top-level sheet (KiCad 10's flat
    "top-level sheets" project feature), linked together purely through the
    written `.kicad_pro`. The highest-priority requested type (`SHEET_TYPE_PRIORITY`)
    gets the project-basename-matching filename and page 1;
    this is a naming/ordering convention only, since the file format itself
    treats every sheet as a peer.
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

    if len(requests) > 1 and KICAD_VERSION < (10, 0, 0):
        msg = (
            "Bundling multiple schematic sheets into one project requires "
            "KiCad 10.0 or higher"
        )
        raise RuntimeError(msg)

    project_path = Path(project_path)
    project_name = project_path.stem

    requests_by_type = {r.sheet_type: r for r in requests}
    planned_filenames = plan_sheet_filenames(project_name, list(requested_types))

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
