# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contract tests for the kipy / IPC API behaviour kbplacer's IPC backend relies on.

See "IPC write model" in `docs/ipc-migration-plan.md`. These pin down current
upstream behaviour, so a failure here means KiCad or kicad-python changed and the write
model has to be revisited. Ported from `tools/ipc_spike/probe_batching.py`.
"""

import logging
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

try:
    from kipy import KiCad
    from kipy.board_types import BoardLayer
    from kipy.geometry import Vector2
    from kipy.kicad import find_kicad_cli
    from kipy.proto.board import board_commands_pb2
    from kipy.proto.board.board_commands_pb2 import BoardFlipDirection
    from kipy.proto.common.commands import editor_commands_pb2
    from kipy.util import pack_any
except ImportError:
    pytest.skip("skipping tests due to missing kipy package", allow_module_level=True)


def _has_api_server() -> bool:
    try:
        cli = find_kicad_cli(None)
        result = subprocess.run(
            [cli, "api-server", "--help"], capture_output=True, check=False
        )
    except Exception:
        return False
    return result.returncode == 0


pytestmark = [
    pytest.mark.ipc,
    pytest.mark.no_ignore_nightly,
    pytest.mark.skipif(
        not _has_api_server(), reason="headless `kicad-cli api-server` not available"
    ),
]

logger = logging.getLogger(__name__)

EXAMPLES = Path(__file__).parents[1] / "examples"
TOP_BOTTOM = BoardFlipDirection.BFD_TOP_BOTTOM
DY = 40_000_000

# kbplacer's SWIG `set_side(BACK)` of SW1 in examples/2x2 on KiCad 10.0.6, numbered pads
# (tools/ipc_spike/swig_reference.kicad-10.0.6.json, case "back")
SWIG_BACK_SW1 = {
    "1": (-3810000, -17610000),
    "2": (2540000, -15070000),
}


@pytest.fixture
def ipc_board(tmpdir):
    """Headless server with a fresh copy of examples/2x2; one project per server"""

    @contextmanager
    def _start():
        root = Path(tmpdir)
        shutil.copytree(EXAMPLES / "examples.pretty", root / "examples.pretty")
        project = root / "2x2"
        project.mkdir()
        for f in ["keyboard-before.kicad_pcb", "fp-lib-table"]:
            shutil.copy(EXAMPLES / "2x2" / f, project / f)
        pcb = project / "keyboard-before.kicad_pcb"
        with KiCad(headless=True, file_path=str(pcb), timeout_ms=20000) as kicad:
            yield kicad, kicad.get_board()

    return _start


def footprints(board):
    return {f.reference_field.text.value: f for f in board.get_footprints()}


def all_pads(fp):
    """Sorted multiset; keying by number would collapse the unnumbered NPTH holes"""
    return sorted((p.number, p.position.x, p.position.y) for p in fp.definition.pads)


def shifted(pads, dy=DY):
    return sorted((n, x, y + dy) for n, x, y in pads)


def flipped_sw1_pads(board):
    """SW1 pads after a top-bottom flip, read back from the server (rolled back)"""
    commit = board.begin_commit()
    board.flip_items([footprints(board)["SW1"]], TOP_BOTTOM)
    pads = all_pads(footprints(board)["SW1"])
    board.drop_commit(commit)
    return pads


def copy_of(fp, dy=0):
    fp.proto.ClearField("id")
    fp.reference_field.text.value = "SW9"
    fp.position = Vector2.from_xy(fp.position.x, fp.position.y + dy)
    return fp


def status_names(results):
    return [editor_commands_pb2.ItemStatusCode.Name(r.status.code) for r in results]


def raw_flip(kicad, board, ids):
    """FlipItems with per-item status, kipy's `flip_items` silently skips failures"""
    cmd = board_commands_pb2.FlipItems()
    cmd.header.document.CopyFrom(board.document)
    cmd.direction = TOP_BOTTOM
    cmd.items.extend(ids)
    resp = kicad._client.send(cmd, board_commands_pb2.FlipItemsResponse)
    return status_names(resp.flipped_items)


def raw_update(kicad, board, items):
    """UpdateItems with per-item status, kipy's `update_items` discards them"""
    cmd = editor_commands_pb2.UpdateItems()
    cmd.header.document.CopyFrom(board.document)
    cmd.items.extend([pack_any(i.proto) for i in items])
    resp = kicad._client.send(cmd, editor_commands_pb2.UpdateItemsResponse)
    return status_names(resp.updated_items)


def test_flip_top_bottom_matches_swig_set_side(ipc_board) -> None:
    # reference for every flip test below
    with ipc_board() as (_, board):
        board.flip_items([footprints(board)["SW1"]], TOP_BOTTOM)
        sw1 = footprints(board)["SW1"]
        assert BoardLayer.Name(sw1.layer) == "BL_B_Cu"
        assert sw1.orientation.degrees == 0
        assert {n: (x, y) for n, x, y in all_pads(sw1) if n} == SWIG_BACK_SW1


# W5: UpdateItems replaces the whole item, updates must come from post-flip re-read


def test_update_from_stale_object_reverts_flip(ipc_board) -> None:
    with ipc_board() as (_, board):
        stale = footprints(board)["SW1"]
        original = all_pads(stale)
        board.flip_items([footprints(board)["SW1"]], TOP_BOTTOM)

        stale.position = Vector2.from_xy(stale.position.x, stale.position.y + DY)
        board.update_items(stale)

        sw1 = footprints(board)["SW1"]
        assert BoardLayer.Name(sw1.layer) == "BL_F_Cu"
        assert all_pads(sw1) == shifted(original)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="kipy `flip_items` refreshes passed objects with pre-flip pad positions; "
    "updating such object moves footprint but not its pads. "
    "If this passes, upstream fixed it and the W5 re-read can be dropped",
)
def test_flip_items_refreshes_passed_object(ipc_board) -> None:
    with ipc_board() as (_, board):
        sw1 = footprints(board)["SW1"]
        board.flip_items([sw1], TOP_BOTTOM)
        assert all_pads(sw1) == all_pads(footprints(board)["SW1"])


@pytest.mark.parametrize("in_commit", [False, True])
def test_update_after_flip_from_reread(ipc_board, in_commit) -> None:
    with ipc_board() as (_, board):
        commit = board.begin_commit() if in_commit else None
        board.flip_items([footprints(board)["SW1"]], TOP_BOTTOM)
        # flips are visible to reads inside an open commit (W7)
        sw1 = footprints(board)["SW1"]
        expected = shifted(all_pads(sw1))

        sw1.position = Vector2.from_xy(sw1.position.x, sw1.position.y + DY)
        board.update_items(sw1)
        if commit:
            board.push_commit(commit, "kbplacer")

        sw1 = footprints(board)["SW1"]
        assert BoardLayer.Name(sw1.layer) == "BL_B_Cu"
        assert all_pads(sw1) == expected


# W11: new back-side footprints have to be created in their final state


def test_flip_and_update_of_item_created_in_same_commit_fail(ipc_board) -> None:
    with ipc_board() as (kicad, board):
        original = all_pads(footprints(board)["SW1"])
        commit = board.begin_commit()
        created = board.create_items([copy_of(footprints(board)["SW1"])])[0]

        assert raw_flip(kicad, board, [created.id]) == ["ISC_NONEXISTENT"]
        created.position = Vector2.from_xy(created.position.x, created.position.y + DY)
        assert raw_update(kicad, board, [created]) == ["ISC_NONEXISTENT"]
        board.push_commit(commit, "kbplacer")

        sw9 = footprints(board)["SW9"]
        assert BoardLayer.Name(sw9.layer) == "BL_F_Cu"
        assert all_pads(sw9) == original


def test_create_already_flipped_copy(ipc_board) -> None:
    with ipc_board() as (_, board):
        expected = shifted(flipped_sw1_pads(board))
        # kbplacer would flip the source on the auxiliary server instead
        commit = board.begin_commit()
        board.flip_items([footprints(board)["SW1"]], TOP_BOTTOM)
        source = footprints(board)["SW1"]  # re-read, see W5
        board.drop_commit(commit)
        target_y = source.position.y + DY

        commit = board.begin_commit()
        board.create_items([copy_of(source, DY)])
        board.push_commit(commit, "kbplacer")

        sw9 = footprints(board)["SW9"]
        assert BoardLayer.Name(sw9.layer) == "BL_B_Cu"
        assert sw9.position.y == target_y
        assert all_pads(sw9) == expected


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="kipy `flip_items` refreshes passed objects with pre-flip pad positions, "
    "a copy created from such object gets pads mirrored at the old position",
)
def test_create_copy_of_flip_refreshed_object(ipc_board) -> None:
    with ipc_board() as (_, board):
        expected = shifted(flipped_sw1_pads(board))
        commit = board.begin_commit()
        source = footprints(board)["SW1"]
        board.flip_items([source], TOP_BOTTOM)
        board.drop_commit(commit)

        board.create_items([copy_of(source, DY)])

        assert all_pads(footprints(board)["SW9"]) == expected


def test_create_then_flip_in_second_commit(ipc_board) -> None:
    # works, but costs two undo steps in the GUI
    with ipc_board() as (kicad, board):
        expected = shifted(flipped_sw1_pads(board))
        commit = board.begin_commit()
        created = board.create_items([copy_of(footprints(board)["SW1"], DY)])[0]
        board.push_commit(commit, "kbplacer: create")

        commit = board.begin_commit()
        assert raw_flip(kicad, board, [created.id]) == ["ISC_OK"]
        board.push_commit(commit, "kbplacer: flip")

        sw9 = footprints(board)["SW9"]
        assert BoardLayer.Name(sw9.layer) == "BL_B_Cu"
        assert all_pads(sw9) == expected
