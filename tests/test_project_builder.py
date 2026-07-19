# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import uuid
from pathlib import Path

from kbplacer.project_builder import create_project_file


def test_single_sheet_project(tmpdir) -> None:
    project_path = Path(tmpdir) / "keyboard.kicad_pro"
    sheet_uuid = str(uuid.uuid4())

    create_project_file(
        project_path,
        sheets=[(sheet_uuid, "keyboard.kicad_sch", "Root")],
    )

    assert project_path.exists()
    with open(project_path, "r") as f:
        project = json.load(f)

    assert project["meta"]["filename"] == "keyboard.kicad_pro"
    assert project["sheets"] == [[sheet_uuid, "Root"]]
    assert project["schematic"]["top_level_sheets"] == [
        {"filename": "keyboard.kicad_sch", "name": "Root", "uuid": sheet_uuid}
    ]


def test_multi_sheet_project_ordering(tmpdir) -> None:
    project_path = Path(tmpdir) / "keyboard.kicad_pro"
    root_uuid = str(uuid.uuid4())
    led_uuid = str(uuid.uuid4())

    create_project_file(
        project_path,
        sheets=[
            (root_uuid, "keyboard.kicad_sch", "Root"),
            (led_uuid, "keyboard-led-chain.kicad_sch", "Led Chain"),
        ],
    )

    with open(project_path, "r") as f:
        project = json.load(f)

    # `sheets` and `schematic.top_level_sheets` must stay in sync, in the same
    # (page) order as passed in.
    assert project["sheets"] == [
        [root_uuid, "Root"],
        [led_uuid, "Led Chain"],
    ]
    assert project["schematic"]["top_level_sheets"] == [
        {"filename": "keyboard.kicad_sch", "name": "Root", "uuid": root_uuid},
        {
            "filename": "keyboard-led-chain.kicad_sch",
            "name": "Led Chain",
            "uuid": led_uuid,
        },
    ]


def test_hierarchical_top_level_sheets_override(tmpdir) -> None:
    # A hierarchical-strategy project: `sheets` lists root + every child, but
    # only the root is a genuine KiCad top-level sheet.
    project_path = Path(tmpdir) / "keyboard.kicad_pro"
    root_uuid = str(uuid.uuid4())
    key_matrix_uuid = str(uuid.uuid4())
    led_uuid = str(uuid.uuid4())

    create_project_file(
        project_path,
        sheets=[
            (root_uuid, "keyboard.kicad_sch", "Root"),
            (key_matrix_uuid, "keyboard-key-matrix.kicad_sch", "Key Matrix"),
            (led_uuid, "keyboard-led-chain.kicad_sch", "Led Chain"),
        ],
        top_level_sheets=[(root_uuid, "keyboard.kicad_sch", "Root")],
    )

    with open(project_path, "r") as f:
        project = json.load(f)

    assert project["sheets"] == [
        [root_uuid, "Root"],
        [key_matrix_uuid, "Key Matrix"],
        [led_uuid, "Led Chain"],
    ]
    assert project["schematic"]["top_level_sheets"] == [
        {"filename": "keyboard.kicad_sch", "name": "Root", "uuid": root_uuid}
    ]


def test_writes_valid_json_with_no_sheets(tmpdir) -> None:
    # Not a realistic call (the orchestrator always passes at least one sheet),
    # but `create_project_file` itself should not assume a non-empty list.
    project_path = Path(tmpdir) / "empty.kicad_pro"

    create_project_file(project_path, sheets=[])

    with open(project_path, "r") as f:
        project = json.load(f)

    assert project["sheets"] == []
    assert project["schematic"]["top_level_sheets"] == []


def test_default_project_is_not_mutated_across_calls(tmpdir) -> None:
    # `DEFAULT_PROJECT` must be deep-copied per call, not mutated in place,
    # or a second invocation would leak the first project's sheets.
    first_path = Path(tmpdir) / "first.kicad_pro"
    second_path = Path(tmpdir) / "second.kicad_pro"

    create_project_file(
        first_path, sheets=[(str(uuid.uuid4()), "first.kicad_sch", "First")]
    )
    create_project_file(second_path, sheets=[])

    with open(second_path, "r") as f:
        second_project = json.load(f)

    assert second_project["sheets"] == []
    assert second_project["schematic"]["top_level_sheets"] == []
