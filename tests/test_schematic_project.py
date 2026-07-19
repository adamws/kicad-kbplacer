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
    resolve_bundle_strategy,
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


def _has_sheet_instances(schematic_path) -> bool:
    with open(schematic_path, "r") as f:
        sch = sexpdata.load(f)
    return any(
        isinstance(item, list)
        and isinstance(item[0], sexpdata.Symbol)
        and item[0].value() == "sheet_instances"
        for item in sch
    )


def _root_sheets(schematic_path) -> list:
    """Return `(sheetname, sheetfile, page)` for each top-level `(sheet ...)`
    block - a hierarchical-strategy root's references to its child sheets."""
    with open(schematic_path, "r") as f:
        sch = sexpdata.load(f)
    entries = []
    for item in sch:
        if not (
            isinstance(item, list)
            and isinstance(item[0], sexpdata.Symbol)
            and item[0].value() == "sheet"
        ):
            continue
        sheetname = sheetfile = page = None
        for sub in item[1:]:
            if not (isinstance(sub, list) and isinstance(sub[0], sexpdata.Symbol)):
                continue
            tag = sub[0].value()
            if tag == "property" and sub[1] == "Sheetname":
                sheetname = sub[2]
            elif tag == "property" and sub[1] == "Sheetfile":
                sheetfile = sub[2]
            elif tag == "instances":
                project_node = sub[1]
                path_node = project_node[2]
                for p in path_node[1:]:
                    if isinstance(p, list) and p[0].value() == "page":
                        page = p[1]
        entries.append((sheetname, sheetfile, page))
    return entries


def _symbol_instance_paths(schematic_path) -> set:
    """Every `path` value used across the file's symbol `(instances ...)`
    blocks - deliberately excludes the top-level `(sheet_instances ...)`
    block, which is a different construct that also nests a `(path ...)`."""
    with open(schematic_path, "r") as f:
        sch = sexpdata.load(f)
    paths = set()

    def walk(node):
        if not isinstance(node, list):
            return
        if (
            node
            and isinstance(node[0], sexpdata.Symbol)
            and node[0].value() == "sheet_instances"
        ):
            return
        if (
            node
            and isinstance(node[0], sexpdata.Symbol)
            and node[0].value() == "path"
            and len(node) > 1
            and isinstance(node[1], str)
        ):
            paths.add(node[1])
        for sub in node:
            walk(sub)

    walk(sch)
    return paths


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
    def test_bundles_both_sheets_flat(self, tmpdir) -> None:
        if KICAD_VERSION < (10, 0, 0):
            pytest.skip("Flat multi-sheet bundling requires KiCad 10.0 or higher")

        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        create_schematic_project(
            project_path,
            layout_file,
            [SchematicRequest("led_chain"), SchematicRequest("key_matrix")],
            strategy="flat",
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

    def test_bundles_both_sheets_hierarchical(self, tmpdir) -> None:
        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        create_schematic_project(
            project_path,
            layout_file,
            [SchematicRequest("led_chain"), SchematicRequest("key_matrix")],
            strategy="hierarchical",
        )

        root_path = Path(tmpdir) / "keyboard.kicad_sch"
        key_matrix_path = Path(tmpdir) / "keyboard-key-matrix.kicad_sch"
        led_path = Path(tmpdir) / "keyboard-led-chain.kicad_sch"
        assert root_path.exists()
        assert key_matrix_path.exists()
        assert led_path.exists()

        # Root is always page 1; children follow SHEET_TYPE_PRIORITY order.
        assert _sheet_page(root_path) == "1"
        root_sheets = {
            name: (filename, page) for name, filename, page in _root_sheets(root_path)
        }
        assert root_sheets["Key Matrix"] == ("keyboard-key-matrix.kicad_sch", "2")
        assert root_sheets["Led Chain"] == ("keyboard-led-chain.kicad_sch", "3")

        # Neither child carries its own sheet_instances - only the root does.
        assert _has_sheet_instances(root_path)
        assert not _has_sheet_instances(key_matrix_path)
        assert not _has_sheet_instances(led_path)

        # Every child symbol's instance path is nested two levels deep:
        # /<root_uuid>/<sheet_block_uuid>, matching the hierarchical-project
        # reference example, not a single-level /<own_uuid> flat-style path.
        root_uuid = _sheet_uuid(root_path)
        for child_path in (key_matrix_path, led_path):
            for path in _symbol_instance_paths(child_path):
                segments = [s for s in path.split("/") if s]
                assert len(segments) == 2
                assert segments[0] == root_uuid

        project = _load_pro(project_path)
        assert [s[1] for s in project["sheets"]] == ["Root", "Key Matrix", "Led Chain"]
        top_level = project["schematic"]["top_level_sheets"]
        # Only the root is a genuine KiCad top-level sheet under this strategy.
        assert len(top_level) == 1
        assert top_level[0]["filename"] == "keyboard.kicad_sch"
        assert top_level[0]["uuid"] == root_uuid
        assert project["sheets"][0][0] == root_uuid

        netlist = generate_netlist(tmpdir, root_path)
        assert netlist.exists()

    def test_flat_strategy_requires_kicad_10_for_multiple_sheets(
        self, tmpdir, monkeypatch
    ) -> None:
        monkeypatch.setattr("kbplacer.schematic_project.KICAD_VERSION", (9, 0, 0))

        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        with pytest.raises(RuntimeError, match="KiCad 10.0"):
            create_schematic_project(
                project_path,
                layout_file,
                [SchematicRequest("key_matrix"), SchematicRequest("led_chain")],
                strategy="flat",
            )

        # Nothing should be written once the gate rejects the request.
        assert not project_path.exists()
        assert not (Path(tmpdir) / "keyboard.kicad_sch").exists()

    def test_default_strategy_succeeds_below_kicad_10(
        self, tmpdir, monkeypatch
    ) -> None:
        # No explicit `strategy`: below KiCad 10 this must auto-resolve to
        # "hierarchical" instead of hitting the flat-only KiCad 10 gate.
        monkeypatch.setattr("kbplacer.schematic_project.KICAD_VERSION", (9, 0, 0))

        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        create_schematic_project(
            project_path,
            layout_file,
            [SchematicRequest("key_matrix"), SchematicRequest("led_chain")],
        )
        assert project_path.exists()
        assert (Path(tmpdir) / "keyboard.kicad_sch").exists()
        assert (Path(tmpdir) / "keyboard-key-matrix.kicad_sch").exists()
        assert (Path(tmpdir) / "keyboard-led-chain.kicad_sch").exists()

    def test_single_type_unrestricted_below_kicad_10(self, tmpdir, monkeypatch) -> None:
        monkeypatch.setattr("kbplacer.schematic_project.KICAD_VERSION", (9, 0, 0))

        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        # A single requested type bypasses the multi-sheet-bundling gate on
        # any supported KiCad version - this test is only about that gate,
        # not about any particular sheet type's own version requirements.
        create_schematic_project(
            project_path,
            layout_file,
            [SchematicRequest("key_matrix")],
        )
        assert project_path.exists()
        assert (Path(tmpdir) / "keyboard.kicad_sch").exists()

    def test_single_sheet_hierarchical_skips_wrapping(self, tmpdir) -> None:
        # With only one requested type there is nothing to bundle: explicit
        # strategy="hierarchical" must produce the same single, self-rooted
        # sheet as "flat" (or an unspecified strategy) would, not a root
        # wrapper around a lone child.
        layout_file = _write_layout(tmpdir)
        project_path = Path(tmpdir) / "keyboard.kicad_pro"

        create_schematic_project(
            project_path,
            layout_file,
            [SchematicRequest("key_matrix")],
            strategy="hierarchical",
        )

        schematic_path = Path(tmpdir) / "keyboard.kicad_sch"
        assert schematic_path.exists()
        assert list(Path(tmpdir).glob("*.kicad_sch")) == [schematic_path]
        assert _has_sheet_instances(schematic_path)
        assert _sheet_page(schematic_path) == "1"

        own_uuid = _sheet_uuid(schematic_path)
        assert _symbol_instance_paths(schematic_path) == {f"/{own_uuid}"}

        project = _load_pro(project_path)
        assert len(project["schematic"]["top_level_sheets"]) == 1


class TestLedOnly:
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

    def test_rejects_unknown_strategy(self, tmpdir) -> None:
        project_path = Path(tmpdir) / "keyboard.kicad_pro"
        with pytest.raises(ValueError, match="Unknown bundle strategy"):
            create_schematic_project(
                project_path,
                "unused",
                [SchematicRequest("key_matrix")],
                strategy="bogus",
            )


class TestResolveBundleStrategy:
    def test_auto_selects_by_kicad_version(self, monkeypatch) -> None:
        monkeypatch.setattr("kbplacer.schematic_project.KICAD_VERSION", (10, 0, 0))
        assert resolve_bundle_strategy(None) == "flat"

        monkeypatch.setattr("kbplacer.schematic_project.KICAD_VERSION", (9, 0, 0))
        assert resolve_bundle_strategy(None) == "hierarchical"

    def test_explicit_value_passes_through(self) -> None:
        assert resolve_bundle_strategy("flat") == "flat"
        assert resolve_bundle_strategy("hierarchical") == "hierarchical"

    def test_rejects_unknown_value(self) -> None:
        with pytest.raises(ValueError, match="Unknown bundle strategy"):
            resolve_bundle_strategy("bogus")
