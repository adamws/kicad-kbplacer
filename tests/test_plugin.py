import logging
import os
import sys
import pcbnew
import pytest

from pathlib import Path


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
