import logging
import os
import sys
from pathlib import Path

import pcbnew
import pytest

logger = logging.getLogger(__name__)


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
def test_if_plugin_registers() -> None:
    from kbplacer.kbplacer_plugin_action import KbplacerPluginAction

    action = KbplacerPluginAction()
    action.register()
    dirname = Path(os.path.realpath(__file__)).parents[1]
    assert (
        action.GetPluginPath()
        == f"{dirname}/kbplacer/kbplacer_plugin_action.py/KbplacerPluginAction"
    )
