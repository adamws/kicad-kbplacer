# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import shutil
import sys
from argparse import ArgumentTypeError
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest

from kbplacer.__main__ import app
from kbplacer.defaults import DEFAULT_DIODE_POSITION, ZERO_POSITION
from kbplacer.element_position import ElementInfo, ElementPosition, PositionOption, Side
from kbplacer.kbplacer_plugin import PluginSettings

logger = logging.getLogger(__name__)


class ExitTest(Exception):
    pass


def get_default(board_path: str) -> PluginSettings:
    """Returns default run settings when using all default CLI values"""
    return PluginSettings(
        pcb_file_path=board_path,
        layout_path="",
        key_info=ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "", start_index=1),
        key_distance=None,  # None when not specified, will use metadata or default (19.05, 19.05)
        diode_info=ElementInfo(
            "D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, ""
        ),
        route_switches_with_diodes=False,  # this in True by default when using GUI
        optimize_diodes_orientation=False,
        route_rows_and_columns=False,  # same as above
        additional_elements=[
            ElementInfo("ST{}", PositionOption.CUSTOM, ZERO_POSITION, "")
        ],
        generate_outline=False,
        outline_delta=0.0,
        template_path="",
        create_pcb_file=False,
        create_sch_file=False,
        sch_file_path="",
        switch_footprint="",
        diode_footprint="",
    )


@pytest.fixture
def cli_isolation(monkeypatch):
    monkeypatch.setattr("kbplacer.__main__.pcbnew.Refresh", MagicMock())
    monkeypatch.setattr("kbplacer.__main__.pcbnew.SaveBoard", MagicMock())

    def mock_exit(*args, **kwargs):
        raise ExitTest(*args, **kwargs)

    monkeypatch.setattr("sys.exit", mock_exit)

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


@contextmanager
def expects_settings(default_difference: Dict):
    # board_path must be set later, it depends on tmpdir
    settings = get_default("")
    for k, v in default_difference.items():
        settings.__setattr__(k, v)
    yield settings


@pytest.mark.parametrize(
    "extra_args,expectation",
    [
        # fmt: off
        # no extra args, expecting run with default options
        (
            [],
            expects_settings({}),
        ),
        # valid switch option values
        #   - valid when only annotation specified
        (
            ["--switch", "S{}"],
            expects_settings({"key_info": ElementInfo("S{}", PositionOption.DEFAULT, ZERO_POSITION, "", start_index=1)}),
        ),
        #   - valid with orientation and side
        (
            ["--switch", "S{} 90 BACK"],
            expects_settings({"key_info": ElementInfo("S{}", PositionOption.DEFAULT,
                                          ElementPosition(0, 0, 90, Side.BACK), "", start_index=1)}),
        ),
        # invalid switch option values
        #   - too many tokens
        (
            ["--switch", "SW{} DEFAULT 0 0 0 FRONT"],
            pytest.raises(ArgumentTypeError,
                match=r"--switch invalid format"
            ),
        ),
        #   - invalid side
        (
            ["--switch", "SW{} 0 NOT_A_SIDE"],
            pytest.raises(ArgumentTypeError,
                match=r"'NOT_A_SIDE' is not a valid Side"
            ),
        ),
        # valid diode option values
        #   - valid relative position setting
        (
            ["--diode", "D{} RELATIVE"],
            expects_settings({"diode_info": ElementInfo("D{}", PositionOption.RELATIVE, None, "")}),
        ),
        #   - valid relative position setting - it is case insensitive
        #     (it is not documented in --help, exist for convenience)
        (
            ["--diode", "D{} rElaTIve"],
            expects_settings({"diode_info": ElementInfo("D{}", PositionOption.RELATIVE, None, "")}),
        ),
        #   - valid relative position setting with destination template save path
        (
            ["--diode", "D{} RELATIVE /path/to/save.kicad_pcb"],
            expects_settings({"diode_info": ElementInfo("D{}", PositionOption.RELATIVE, None,
                                                        "/path/to/save.kicad_pcb")}),
        ),
        #   - valid preset with path (CLI does not check if file exist, this is done later)
        (
            ["--diode", "D{} PRESET /path/to/load.kicad_pcb"],
            expects_settings({"diode_info": ElementInfo("D{}", PositionOption.PRESET, None,
                                                        "/path/to/load.kicad_pcb")}),
        ),
        #   - valid custom position setting
        (
            ["--diode", "DIODE{} CUSTOM 1.5 -2.05 180.0 FRONT"],
            expects_settings({"diode_info": ElementInfo("DIODE{}", PositionOption.CUSTOM,
                                            ElementPosition(1.5, -2.05, 180.0, Side.FRONT), "")}),
        ),
        #   - valid custom position setting with side lowercase
        (
            ["--diode", "DIODE{} CUSTOM 1.5 -2.05 180.0 front"],
            expects_settings({"diode_info": ElementInfo("DIODE{}", PositionOption.CUSTOM,
                                            ElementPosition(1.5, -2.05, 180.0, Side.FRONT), "")}),
        ),
        # invalid diode option values
        #   - invalid position
        (
            ["--diode", "D{} NO_SUCH_OPTION"],
            pytest.raises(ArgumentTypeError,
                match=r"'NO_SUCH_OPTION' is not a valid PositionOption"
            ),
        ),
        #   - too little tokens
        (
            ["--diode", "D{}"],
            pytest.raises(ArgumentTypeError,
                match=r"--diode invalid format"
            ),
        ),
        #   - too many tokens
        (
            ["--diode", "D{} CUSTOM 0 0 0 FRONT 90"],
            pytest.raises(ArgumentTypeError,
                match=r"--diode invalid format"
            ),
        ),
        #   - invalid float numbers
        (
            ["--diode", "D{} CUSTOM 0 --10 0 FRONT"],
            pytest.raises(ArgumentTypeError,
                          match=r"could not convert string to float: '--10'"
            ),
        ),
        #   - annotation without placeholder
        (
            ["--diode", "D CUSTOM 0 0 0 FRONT"],
            pytest.raises(ArgumentTypeError,
                match=r"'D' invalid annotation specifier"
            ),
        ),
        #   - valid option with missing details
        (
            ["--diode", "D{} CUSTOM"],
            pytest.raises(ArgumentTypeError,
                match=r"needs to be equal RELATIVE or DEFAULT if position details not provided"
            ),
        ),
        #   - valid option with incomplete details
        #      '0' would be interpreted as template path, making CUSTOM illegal choice
        (
            ["--diode", "D{} CUSTOM 0"],
            pytest.raises(ArgumentTypeError,
                match=r"needs to be equal RELATIVE or PRESET when providing template path"
            ),
        ),
        #   - details with wrong option
        (
            ["--diode", "D{} PRESET 0 0 0 FRONT"],
            pytest.raises(ArgumentTypeError,
                match=r"needs to be equal CUSTOM when providing position details"
            ),
        ),
        # valid additional elements option values
        #   - valid relative position setting
        (
            ["--additional-elements", "LED{} RELATIVE;ST{} CUSTOM 0 0 0 FRONT"],
            expects_settings({"additional_elements": [
                ElementInfo("LED{}", PositionOption.RELATIVE, None, ""),
                ElementInfo("ST{}", PositionOption.CUSTOM, ZERO_POSITION, ""),
            ]}),
        ),
        # invalid additional elements option values
        #   - wrong separator
        (
            ["--additional-elements", "LED{} RELATIVE:ST{} CUSTOM 0 0 0 FRONT"],
            pytest.raises(ArgumentTypeError,
                match=r"--additional-elements invalid format."
            ),
        ),
        #   - using DEFAULT position
        (
            ["--additional-elements", "LED{} DEFAULT"],
            pytest.raises(ArgumentTypeError,
                match=r"--additional-elements does not support DEFAULT position"
            ),
        ),
        # valid key-distance option values
        #   - integers
        (
            ["--key-distance", "18 18"],
            expects_settings({"key_distance": (18, 18)}),
        ),
        #   - floats
        (
            ["--key-distance", "18.05 19.05"],
            expects_settings({"key_distance": (18.05, 19.05)}),
        ),
        # invalid key-distance option values
        #   - wrong separator # TODO: error message could be better
        (
            ["--key-distance", "18,18"],
            pytest.raises(ArgumentTypeError,
                match=r"could not convert string to float: '18,18'"
            ),
        ),
        #   - too many tokens
        (
            ["--key-distance", "18 18 18"],
            pytest.raises(ArgumentTypeError,
                match=r"--key-distance must be exactly two numeric values separated by a space."
            ),
        ),
        # some more complex scenarios combining multiple options:
        (
            ["--key-distance", "18 18.05", "--diode", "DIODE{} CUSTOM 1.5 -2.05 180.0 FRONT",
             "--template", "/some/path", "--route-switches-with-diodes", "--route-rows-and-columns"],
            expects_settings({"diode_info": ElementInfo("DIODE{}", PositionOption.CUSTOM,
                                            ElementPosition(1.5, -2.05, 180.0, Side.FRONT), ""),
                              "key_distance": (18, 18.05),
                              "template_path": "/some/path",
                              "route_switches_with_diodes": True,
                              "route_rows_and_columns": True,
                              }),
        ),
        # valid footprint identifier option values
        #   - valid switch footprint
        (
            ["--switch-footprint", "/usr/share/kicad/footprints/Button_Switch_Keyboard.pretty:SW_Cherry_MX_1.00u_PCB"],
            expects_settings({"switch_footprint": "/usr/share/kicad/footprints/Button_Switch_Keyboard.pretty:SW_Cherry_MX_1.00u_PCB"}),
        ),
        #   - valid diode footprint
        (
            ["--diode-footprint", "/usr/share/kicad/footprints/Diode_SMD.pretty:D_SOD-123F"],
            expects_settings({"diode_footprint": "/usr/share/kicad/footprints/Diode_SMD.pretty:D_SOD-123F"}),
        ),
        #   - valid with relative path
        (
            ["--switch-footprint", "footprints/MyLib.pretty:MyFootprint"],
            expects_settings({"switch_footprint": "footprints/MyLib.pretty:MyFootprint"}),
        ),
        #   - both footprints specified
        (
            ["--switch-footprint", "/path/to/switches.pretty:SW_MX",
             "--diode-footprint", "/path/to/diodes.pretty:D_SOD123"],
            expects_settings({"switch_footprint": "/path/to/switches.pretty:SW_MX",
                              "diode_footprint": "/path/to/diodes.pretty:D_SOD123"}),
        ),
        # invalid footprint identifier option values
        #   - missing colon
        (
            ["--switch-footprint", "/path/to/library.pretty/FootprintName"],
            pytest.raises(ArgumentTypeError,
                match=r"invalid footprint identifier, it must contain at least one ':' separator"
            ),
        ),
        #   - multiple colons
        (
            ["--switch-footprint", "/path/to/library.pretty:Footprint{:.2f}"],
            expects_settings({"switch_footprint": "/path/to/library.pretty:Footprint{:.2f}"})
        ),
        #   - library path doesn't end with .pretty
        (
            ["--switch-footprint", "/path/to/library:FootprintName"],
            pytest.raises(ArgumentTypeError,
                match=r"invalid footprint identifier, library path must end with '.pretty'"
            ),
        ),
        #   - library path has .pretty in the middle but not at the end
        (
            ["--switch-footprint", "/path/to/library.pretty/subdir:FootprintName"],
            pytest.raises(ArgumentTypeError,
                match=r"invalid footprint identifier, library path must end with '.pretty'"
            ),
        ),
        #   - empty footprint name
        (
            ["--diode-footprint", "/path/to/library.pretty:"],
            pytest.raises(ArgumentTypeError,
                match=r"invalid footprint identifier, footprint name cannot be empty"
            ),
        ),
        # Windows-style paths
        #   - valid Windows path with drive letter C:\
        (
            ["--switch-footprint", r"C:\kicad\footprints\Button_Switch_Keyboard.pretty:SW_Cherry_MX"],
            expects_settings({"switch_footprint": r"C:\kicad\footprints\Button_Switch_Keyboard.pretty:SW_Cherry_MX"}),
        ),
        #   - valid Windows path with different drive letter
        (
            ["--diode-footprint", r"D:\libraries\Diode_SMD.pretty:D_SOD-123F"],
            expects_settings({"diode_footprint": r"D:\libraries\Diode_SMD.pretty:D_SOD-123F"}),
        ),
        #   - valid Windows path with footprint name containing colons
        (
            ["--switch-footprint", r"C:\path\to\library.pretty:Footprint{:.2f}"],
            expects_settings({"switch_footprint": r"C:\path\to\library.pretty:Footprint{:.2f}"}),
        ),
        #   - valid Windows path with multiple directory levels
        (
            ["--switch-footprint", r"C:\Users\Username\Documents\kicad\footprints\MyLib.pretty:MyFootprint"],
            expects_settings({"switch_footprint": r"C:\Users\Username\Documents\kicad\footprints\MyLib.pretty:MyFootprint"}),
        ),
        #   - invalid Windows path missing second colon separator
        (
            ["--switch-footprint", r"C:\kicad\footprints\library.pretty"],
            pytest.raises(ArgumentTypeError,
                match=r"invalid footprint identifier, Windows path must contain ':' separator after library path"
            ),
        ),
        #   - Windows path with empty footprint name
        (
            ["--diode-footprint", r"C:\path\to\library.pretty:"],
            pytest.raises(ArgumentTypeError,
                match=r"invalid footprint identifier, footprint name cannot be empty"
            ),
        ),
        #   - Windows path without .pretty extension
        (
            ["--switch-footprint", r"C:\kicad\footprints\library:FootprintName"],
            pytest.raises(ArgumentTypeError,
                match=r"invalid footprint identifier, library path must end with '.pretty'"
            ),
        ),
        # valid --start-index option values
        (
            ["--start-index", "0"],
            expects_settings({"key_info": ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "", start_index=0)}),
        ),
        (
            ["--start-index", "10"],
            expects_settings({"key_info": ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "", start_index=10)}),
        ),
        # --start-index combined with custom switch annotation
        (
            ["--switch", "K{} 90 BACK", "--start-index", "5"],
            expects_settings({
                "key_info": ElementInfo(
                    "K{}",
                    PositionOption.DEFAULT,
                    ElementPosition(0, 0, 90, Side.BACK),
                    "",
                    start_index=5
                ),
            }),
        ),
        # fmt: on
    ],
)
def test_cli_arguments(
    monkeypatch, cli_isolation, fake_board, extra_args, expectation
) -> None:
    run_mock = Mock()
    monkeypatch.setattr("kbplacer.__main__.run_board", run_mock)

    args = ["--pcb-file", fake_board] + extra_args
    with cli_isolation(args):
        with expectation as s:
            app()

        if isinstance(s, PluginSettings):
            s.pcb_file_path = fake_board
            run_mock.assert_called_once_with(s)
        else:
            run_mock.assert_not_called()


def test_board_creation_when_exist(
    caplog, monkeypatch, cli_isolation, fake_board
) -> None:
    run_mock = Mock()
    monkeypatch.setattr("kbplacer.__main__.run_board", run_mock)

    args = ["--pcb-file", fake_board, "--create-pcb-file"]
    with cli_isolation(args):
        with pytest.raises(ExitTest):
            app()

    run_mock.assert_not_called()
    assert caplog.records[0].message == f"File {fake_board} already exist, aborting"


def test_schematic_creation_when_exist(
    caplog, monkeypatch, cli_isolation, fake_board
) -> None:
    run_mock = Mock()
    monkeypatch.setattr("kbplacer.__main__.run_schematic", run_mock)

    fake_schematic = Path(fake_board).with_suffix(".kicad_sch")
    args = ["--pcb-file", fake_board, "--create-sch-file"]
    with cli_isolation(args):
        shutil.copy(fake_board, fake_schematic)
        with pytest.raises(ExitTest):
            app()

    run_mock.assert_not_called()
    assert caplog.records[0].message == f"File {fake_schematic} already exist, aborting"


def test_max_keys_validation_passes(monkeypatch, cli_isolation, fake_board) -> None:
    """Test that max-keys validation passes when key count is within limit"""
    run_mock = Mock()
    monkeypatch.setattr("kbplacer.__main__.run_board", run_mock)

    # Use 2x2 layout which has 4 keys
    layout_path = "tests/data/ergogen-layouts/2x2.json"
    args = ["--pcb-file", fake_board, "--layout", layout_path, "--max-keys", "4"]
    with cli_isolation(args):
        app()

    # Should succeed and call run_board
    run_mock.assert_called_once()


def test_max_keys_validation_fails(
    caplog, monkeypatch, cli_isolation, fake_board
) -> None:
    """Test that max-keys validation fails when key count exceeds limit"""
    run_mock = Mock()
    monkeypatch.setattr("kbplacer.__main__.run_board", run_mock)

    # Use 2x2 layout which has 4 keys
    layout_path = "tests/data/ergogen-layouts/2x2.json"
    args = ["--pcb-file", fake_board, "--layout", layout_path, "--max-keys", "3"]
    with cli_isolation(args):
        with pytest.raises(ExitTest):
            app()

    run_mock.assert_not_called()
    # Find the error record
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) > 0
    assert (
        "Layout has 4 keys, which exceeds the maximum of 3" in error_records[0].message
    )
