# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from pathlib import Path

import pytest
import sexpdata

from kbplacer.schematic_project import (
    SHEET_TYPE_PRIORITY,
    SchematicRequest,
    create_schematic_project,
)

from .conftest import (
    KICAD_VERSION,
    generate_netlist,
    generate_schematic_image,
)

LAYOUT = [["0,0", "0,1"], ["1,0", "1,1"]]


def _write_layout(tmpdir) -> Path:
    layout_file = Path(tmpdir) / "layout.json"
    with open(layout_file, "w") as f:
        json.dump(LAYOUT, f)
    return layout_file


def _load_pro(project_path) -> dict:
    with open(project_path, "r") as f:
        return json.load(f)


def _sheet_uuid(schematic_path) -> str:
    with open(schematic_path, "r") as f:
        sch = sexpdata.load(f)
    # top-level (uuid ...): (kicad_sch (version ...) (uuid "...") ...)
    for item in sch:
        if isinstance(item, list) and isinstance(item[0], sexpdata.Symbol):
            if item[0].value() == "uuid":
                return item[1]
    return None


def _sheet_page(schematic_path) -> str:
    with open(schematic_path, "r") as f:
        sch = sexpdata.load(f)
    for item in sch:
        if (
            isinstance(item, list)
            and isinstance(item[0], sexpdata.Symbol)
            and item[0].value() == "sheet_instances"
        ):
            path_node = item[1]
            for sub in path_node[1:]:
                if isinstance(sub, list) and sub[0].value() == "page":
                    return sub[1]
    return None


pytestmark = pytest.mark.skipif(
    KICAD_VERSION < (9, 0, 0), reason="Requires KiCad 9.0 or higher"
)


class TestKeyMatrixOnly:
    def test_matches_single_sheet_output(self, tmpdir) -> None:
        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        create_schematic_project(
            project_path,
            layout_file,
            [SchematicRequest("key_matrix")],
        )

        schematic_path = Path(tmpdir) / "keyboard.kicad_sch"
        assert schematic_path.exists()
        assert project_path.exists()
        # No other sheet is written for a single-type request.
        assert list(Path(tmpdir).glob("*.kicad_sch")) == [schematic_path]

        project = _load_pro(project_path)
        assert len(project["sheets"]) == 1
        assert len(project["schematic"]["top_level_sheets"]) == 1
        assert project["sheets"][0][0] == _sheet_uuid(schematic_path)
        assert _sheet_page(schematic_path) == "1"

        generate_schematic_image(tmpdir, schematic_path)
        netlist = generate_netlist(tmpdir, schematic_path)
        assert netlist.exists()


class TestKeyMatrixAndLed:
    def test_bundles_both_sheets(self, tmpdir) -> None:
        if KICAD_VERSION < (10, 0, 0):
            pytest.skip("Multi-sheet bundling requires KiCad 10.0 or higher")

        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        create_schematic_project(
            project_path,
            layout_file,
            [SchematicRequest("led_chain"), SchematicRequest("key_matrix")],
        )

        primary_path = Path(tmpdir) / "keyboard.kicad_sch"
        led_path = Path(tmpdir) / "keyboard-led-chain.kicad_sch"
        assert primary_path.exists()
        assert led_path.exists()

        # Key matrix outranks LED chain in SHEET_TYPE_PRIORITY, so it must be
        # the primary sheet (basename-matching filename, page 1) regardless of
        # the order requests were passed in.
        assert SHEET_TYPE_PRIORITY.index("key_matrix") < SHEET_TYPE_PRIORITY.index(
            "led_chain"
        )
        assert _sheet_page(primary_path) == "1"
        assert _sheet_page(led_path) == "2"

        project = _load_pro(project_path)
        assert [s[1] for s in project["sheets"]] == ["Key Matrix", "Led Chain"]
        top_level = project["schematic"]["top_level_sheets"]
        assert [s["filename"] for s in top_level] == [
            "keyboard.kicad_sch",
            "keyboard-led-chain.kicad_sch",
        ]

        # Each file's own top-level uuid must match its .kicad_pro entry.
        primary_uuid = _sheet_uuid(primary_path)
        led_uuid = _sheet_uuid(led_path)
        assert project["sheets"][0][0] == primary_uuid
        assert project["sheets"][1][0] == led_uuid
        assert top_level[0]["uuid"] == primary_uuid
        assert top_level[1]["uuid"] == led_uuid
        assert primary_uuid != led_uuid

        generate_schematic_image(tmpdir, primary_path)
        netlist = generate_netlist(tmpdir, primary_path)
        assert netlist.exists()

    def test_requires_kicad_10_for_multiple_sheets(self, tmpdir, monkeypatch) -> None:
        monkeypatch.setattr("kbplacer.schematic_project.KICAD_VERSION", (9, 0, 0))

        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        with pytest.raises(RuntimeError, match="KiCad 10.0"):
            create_schematic_project(
                project_path,
                layout_file,
                [SchematicRequest("key_matrix"), SchematicRequest("led_chain")],
            )

        # Nothing should be written once the gate rejects the request.
        assert not project_path.exists()
        assert not (Path(tmpdir) / "keyboard.kicad_sch").exists()

    def test_single_type_unrestricted_below_kicad_10(self, tmpdir, monkeypatch) -> None:
        monkeypatch.setattr("kbplacer.schematic_project.KICAD_VERSION", (9, 0, 0))

        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        # A single requested type bypasses the multi-sheet-bundling gate on
        # any supported KiCad version. Uses "key_matrix" rather than
        # "led_chain" here since the LED-chain schematic itself is KiCad 10
        # only (its template requires KiCad 10 schema features) regardless
        # of bundling - this test is only about the bundling gate.
        create_schematic_project(
            project_path,
            layout_file,
            [SchematicRequest("key_matrix")],
        )
        assert project_path.exists()
        assert (Path(tmpdir) / "keyboard.kicad_sch").exists()


class TestLedOnly:
    @pytest.mark.skipif(
        KICAD_VERSION < (10, 0, 0), reason="Requires KiCad 10.0 or higher"
    )
    def test_led_only_becomes_primary(self, tmpdir) -> None:
        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        create_schematic_project(
            project_path,
            layout_file,
            [SchematicRequest("led_chain")],
        )

        schematic_path = Path(tmpdir) / "keyboard.kicad_sch"
        assert schematic_path.exists()
        assert _sheet_page(schematic_path) == "1"

        project = _load_pro(project_path)
        assert len(project["sheets"]) == 1
        assert project["sheets"][0][1] == "Led Chain"

    @pytest.mark.skipif(
        KICAD_VERSION < (10, 0, 0), reason="Requires KiCad 10.0 or higher"
    )
    def test_visual_wt60_a(self, request, tmpdir) -> None:
        """Not a correctness check. `LAYOUT` (used by every other test in this
        file) only has 4 keys, far below the ~9-14 LEDs/row that force the LED
        chain and capacitor bank to wrap into multiple rows - the trickiest
        part of `led_schematic_builder`'s layout code. wt60_a is a real 60%
        layout with 63 physical key positions, comfortably large enough to
        exercise that wrapping.

        Asserting the generated wiring is correct would mean reimplementing
        the layout/routing logic in the test, so instead this just renders the
        sheet to the HTML test report
        """
        test_dir = request.fspath.dirname
        layout_file = Path(test_dir) / "data/via-layouts/wt60_a.json"
        project_path = Path(tmpdir) / "wt60_a.kicad_pro"

        create_schematic_project(
            project_path,
            layout_file,
            [SchematicRequest("led_chain")],
        )

        schematic_path = Path(tmpdir) / "wt60_a.kicad_sch"
        assert schematic_path.exists()

        generate_schematic_image(tmpdir, schematic_path)


class TestValidation:
    def test_rejects_empty_requests(self, tmpdir) -> None:
        project_path = Path(tmpdir) / "keyboard.kicad_pro"
        with pytest.raises(ValueError, match="At least one"):
            create_schematic_project(project_path, "unused", [])

    def test_rejects_unknown_type(self, tmpdir) -> None:
        project_path = Path(tmpdir) / "keyboard.kicad_pro"
        with pytest.raises(ValueError, match="Unknown schematic type"):
            create_schematic_project(
                project_path, "unused", [SchematicRequest("bogus")]
            )

    def test_mcu_not_implemented_yet(self, tmpdir) -> None:
        project_path = Path(tmpdir) / "keyboard.kicad_pro"
        with pytest.raises(NotImplementedError):
            create_schematic_project(project_path, "unused", [SchematicRequest("mcu")])
