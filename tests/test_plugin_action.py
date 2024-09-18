import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pcbnew
import pytest

from kbplacer.kbplacer_plugin_action import KbplacerPluginAction

logger = logging.getLogger(__name__)


@pytest.fixture()
def kbplacer_plugin_action():
    action = KbplacerPluginAction()
    action.register()
    yield action
    action.deregister()


@pytest.mark.run_first
@pytest.mark.no_ignore_nightly
def test_if_plugin_loads() -> None:
    version = pcbnew.Version()
    logger.info(f"Plugin executed with KiCad version: {version}")
    logger.info(f"Plugin executed with python version: {repr(sys.version)}")

    dirname = Path(os.path.realpath(__file__)).parents[1]
    pcbnew.LoadPluginModule(dirname, "kbplacer", "")
    not_loaded = pcbnew.GetUnLoadableWizards()
    assert not_loaded == "", pcbnew.GetWizardsBackTrace()


@pytest.mark.skipif(sys.platform == "win32", reason="fails on windows")
def test_if_plugin_registers(kbplacer_plugin_action) -> None:
    dirname = Path(os.path.realpath(__file__)).parents[1]
    assert (
        kbplacer_plugin_action.GetPluginPath()
        == f"{dirname}/kbplacer/kbplacer_plugin_action.py/KbplacerPluginAction"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="fails on windows")
@patch("pcbnew.GetBoard")
def test_if_plugin_initializes_with_board(
    mock_get_board: MagicMock, tmpdir, kbplacer_plugin_action
) -> None:
    mock_board = MagicMock()
    mock_board.GetFileName.return_value = f"{tmpdir}/test_board.kicad_pcb"

    mock_get_board.return_value = mock_board
    kbplacer_plugin_action.initialize()
    assert Path(tmpdir / "kbplacer.log").is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="fails on windows")
@patch("pcbnew.GetBoard")
def test_if_plugin_not_initializes_without_board(
    mock_get_board: MagicMock, kbplacer_plugin_action
) -> None:
    mock_board = MagicMock()
    mock_board.GetFileName.return_value = ""

    mock_get_board.return_value = mock_board
    with pytest.raises(Exception, match="Could not locate .kicad_pcb file.*"):
        kbplacer_plugin_action.initialize()
