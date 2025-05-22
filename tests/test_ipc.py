import json
import logging
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pcbnew
import pytest

from .conftest import KICAD_VERSION, add_switch_footprint

try:
    import kipy
except ImportError:
    pytest.skip("skipping tests due to missing kipy package", allow_module_level=True)

logger = logging.getLogger(__name__)


def get_kicad_config_dir(is_nightly: bool) -> Path:
    assert KICAD_VERSION
    major = KICAD_VERSION[0]
    version_str = f"{major}.99" if is_nightly else f"{major}.0"
    return (
        Path.home()
        / ("AppData/Roaming" if sys.platform == "win32" else ".config")
        / f"kicad/{version_str}"
    )


def prepare_mock_fp_lib_table(is_nightly: bool) -> None:
    # create mock fp-lib-table file in config dir if does not already exist
    # this avoid popup on first pcbnew run

    fp_lib_table_path = get_kicad_config_dir(is_nightly) / "fp-lib-table"

    if not Path(fp_lib_table_path).is_file():
        with open(fp_lib_table_path, "w") as f:
            f.write("(fp_lib_table)")


def enable_ipc_api(is_nightly: bool) -> None:
    settings_file = get_kicad_config_dir(is_nightly) / "kicad_common.json"
    if not settings_file.is_file():
        # most likely pcbnew never executed, create minimal config
        with open(settings_file, "w") as f:
            logger.info("Create minimal settings file")
            min_settings = {
                "api": {"enable_server": True, "interpreter_path": ""},
                "do_not_show_again": {
                    "data_collection_prompt": True,
                    "update_check_prompt": True,
                },
            }
            json.dump(min_settings, f, indent=2)
    else:
        with open(settings_file, "r") as f:
            settings = json.load(f)

        modified = False
        if not settings["api"]["enable_server"]:
            logger.info("Enable IPC API")
            settings["api"]["enable_server"] = True
            modified = True
        prompts = ["data_collection_prompt", "update_check_prompt"]
        for prompt in prompts:
            if not settings["do_not_show_again"][prompt]:
                logger.info(f"Disable '{prompt}' prompt")
                settings["do_not_show_again"][prompt] = True
                modified = True

        if modified:
            with open(settings_file, "w") as f:
                json.dump(settings, f, indent=2)


@pytest.fixture
def pcbnew_app():
    is_nightly = pcbnew.IsNightlyVersion()
    prepare_mock_fp_lib_table(is_nightly)
    enable_ipc_api(is_nightly)
    if is_nightly:
        if sys.platform == "win32":
            raise RuntimeError("Unsupported configuration")
        else:
            return "/usr/lib/kicad-nightly/bin/pcbnew"
    return "pcbnew"


def wait_for_kicad(kicad, timeout: float, interval: float = 1.0):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            kicad.ping()
            return
        except (kipy.errors.ApiError, kipy.errors.ConnectionError):
            pass
        time.sleep(interval)

    raise TimeoutError(f"KiCad did not respond within {timeout} seconds.")


@pytest.fixture
def background_kicad(tmpdir, screen_manager, pcbnew_app):
    @contextmanager
    def _background(pcb_path: str = ""):
        with screen_manager as mgr:
            env = os.environ.copy()
            args = [pcbnew_app]
            if pcb_path:
                args.append(pcb_path)
            p = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                env=env,
            )

            kicad = kipy.KiCad()
            wait_for_kicad(kicad, 10, 0.2)

            yield kicad

            _ = mgr.screenshot("", f"{tmpdir}/report/screenshot.png")
            p.kill()
            outs, errs = p.communicate()

            logger.info(f"Process stdout: {outs}")
            logger.info(f"Process stderr: {errs}")

    yield _background


@pytest.mark.skipif(KICAD_VERSION < (9, 0, 0), reason="IPC API not available")
def test_kicad_connection(background_kicad) -> None:
    with background_kicad() as kicad:
        version = kicad.get_version()
        logger.info(f"KiCad version: {version}")

        version_tuple = (version.major, version.minor, version.patch)
        assert version_tuple >= (9, 0, 0)


def get_board_with_one_footprint(request, footprint: str) -> pcbnew.BOARD:
    board = pcbnew.CreateEmptyBoard()
    _ = add_switch_footprint(board, request, 1, footprint=footprint)
    return board


@pytest.mark.skipif(KICAD_VERSION < (9, 0, 0), reason="IPC API not available")
@pytest.mark.xfail
def test_footprint_move(request, tmpdir, background_kicad) -> None:
    board = get_board_with_one_footprint(request, "SW_Cherry_MX_PCB_1.00u")

    footprint = board.FindFootprintByReference("SW1")
    pads_initial_positions = [p.GetPosition() for p in footprint.Pads()]
    pads_initial_positions = sorted(pads_initial_positions)

    pcb_path = f"{tmpdir}/test.kicad_pcb"
    board.Save(pcb_path)

    dest_x = 5 * 10**6
    dest_y = dest_x

    with background_kicad(pcb_path) as kicad:
        b = kicad.get_board()
        footprints = b.get_footprints()
        assert len(footprints) == 1
        sw = footprints[0]
        assert sw.reference_field.text.as_text().value == "SW1"
        sw.position = kipy.geometry.Vector2.from_xy(dest_x, dest_y)
        b.update_items(sw)
        b.save()

    board = pcbnew.LoadBoard(pcb_path)
    footprint = board.FindFootprintByReference("SW1")
    position = footprint.GetPosition()
    assert position.x == dest_x
    assert position.y == dest_y

    # add more strict check, seems that IPC API is bugged and code above just changes
    # footprint origin (pads positions are unchanged) - checked with KiCad 9.0.2
    # and kicad-python 0.3.0
    pads_final_positions = [p.GetPosition() for p in footprint.Pads()]
    pads_final_positions = sorted(pads_final_positions)
    assert pads_final_positions != pads_initial_positions

