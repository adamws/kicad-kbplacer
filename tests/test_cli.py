import logging
import sys
from contextlib import contextmanager
from typing import List
from unittest.mock import MagicMock, Mock, patch

import pytest

from kbplacer.__main__ import app
from kbplacer.defaults import DEFAULT_DIODE_POSITION, ZERO_POSITION
from kbplacer.element_position import ElementInfo, PositionOption
from kbplacer.kbplacer_plugin import PluginSettings

logger = logging.getLogger(__name__)


def get_default(board_path: str) -> PluginSettings:
    """Returns default run settings when using all default CLI values"""
    return PluginSettings(
        board_path=board_path,
        layout_path="",
        key_info=ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, ""),
        key_distance=(19.05, 19.05),
        diode_info=ElementInfo(
            "D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, ""
        ),
        route_switches_with_diodes=False,  # this in True by default when using GUI
        route_rows_and_columns=False,  # same as above
        additional_elements=[
            ElementInfo("ST{}", PositionOption.CUSTOM, ZERO_POSITION, "")
        ],
        generate_outline=False,
        outline_delta=0.0,
        template_path="",
        create_from_annotated_layout=False,
        switch_footprint="",
        diode_footprint="",
    )


@pytest.fixture
def cli_isolation(monkeypatch):
    monkeypatch.setattr("kbplacer.__main__.pcbnew.Refresh", MagicMock())
    monkeypatch.setattr("kbplacer.__main__.pcbnew.SaveBoard", MagicMock())

    @contextmanager
    def _isolation(args: List):
        args.insert(0, "")
        with patch.object(sys, "argv", args):
            yield

    yield _isolation


@pytest.fixture
def fake_board(tmpdir) -> str:
    board_path = f"{tmpdir}/example.kicad_pcb"
    with open(board_path, "w") as f:
        # content not important, we just need file,
        # running actions on this file is mocked
        f.write("")
    return board_path


def test_board_path_with_all_defaults(monkeypatch, cli_isolation, fake_board) -> None:
    run_mock = Mock()
    monkeypatch.setattr("kbplacer.__main__.run", run_mock)

    args = ["--board", fake_board]
    with cli_isolation(args):
        app()

    run_mock.assert_called_once_with(get_default(fake_board))
