# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import copy
import json
import os
from typing import List, Optional, Tuple

# Minimal-but-valid default `.kicad_pro`
DEFAULT_PROJECT = {
    "board": {
        "design_settings": {
            "defaults": {},
            "diff_pair_dimensions": [],
            "drc_exclusions": [],
            "rules": {},
            "track_widths": [],
            "via_dimensions": [],
        }
    },
    "boards": [],
    "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
    "meta": {"filename": "kicad.kicad_pro", "version": 1},
    "net_settings": {"classes": [], "meta": {"version": 0}},
    "pcbnew": {"page_layout_descr_file": ""},
    "schematic": {
        "annotate_start_num": 0,
        "annotation": {
            "method": 0,
            "sort_order": 0,
        },
        "legacy_lib_dir": "",
        "legacy_lib_list": [],
        "meta": {
            "version": 1,
        },
        "page_layout_descr_file": "",
        "plot_directory": "",
        "reuse_designators": True,
        "subpart_first_id": 65,
        "subpart_id_separator": 0,
        "top_level_sheets": [],
        "used_designators": "",
        "variants": [],
    },
    "tuning_profiles": {
        "meta": {
            "version": 0,
        },
        "tuning_profiles_impedance_geometric": [],
    },
    "sheets": [],
    "text_variables": {},
}


def create_project_file(
    project_path,
    *,
    sheets: List[Tuple[str, str, str]],
    top_level_sheets: Optional[List[Tuple[str, str, str]]] = None,
) -> None:
    """Write a minimal-but-valid `.kicad_pro` bundling `sheets` as top-level sheets.

    `sheets` is a list of `(uuid, filename, display_name)` tuples, in page order
    (the order KiCad's project navigator will list them, and the order pages are
    numbered from 1).

    `top_level_sheets` (same tuple shape) controls the `schematic.top_level_sheets`
    entries written to the `.kicad_pro` and defaults to `sheets` when omitted -
    the flat-bundling case, where every bundled sheet is its own top-level sheet.
    A hierarchical bundling caller passes a single-entry `top_level_sheets`
    (the root sheet only) while `sheets` still lists root + every child, since
    only the root is a genuine KiCad top-level sheet in that layout.
    """
    if top_level_sheets is None:
        top_level_sheets = sheets

    project = copy.deepcopy(DEFAULT_PROJECT)
    project["meta"]["filename"] = os.path.basename(project_path)
    project["sheets"] = [[uid, name] for uid, _filename, name in sheets]
    project["schematic"]["top_level_sheets"] = [
        {"filename": filename, "name": name, "uuid": uid}
        for uid, filename, name in top_level_sheets
    ]
    with open(project_path, "w") as f:
        json.dump(project, f, indent=2)
        f.write("\n")
