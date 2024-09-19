from __future__ import annotations

import copy
import json
import logging
from typing import List, Tuple

import pcbnew
import pytest

from kbplacer.board_modifier import (
    get_footprint,
    get_orientation,
    get_position,
    get_side,
    set_position,
    set_rotation,
    set_side,
)
from kbplacer.defaults import DEFAULT_DIODE_POSITION, ZERO_POSITION
from kbplacer.element_position import ElementInfo, PositionOption, Side
from kbplacer.key_placer import (
    KeyboardSwitchIterator,
    KeyMatrix,
    KeyPlacer,
)
from kbplacer.kle_serial import get_keyboard
from kbplacer.plugin_error import PluginError

from .conftest import (
    KICAD_VERSION,
    add_diode_footprint,
    add_led_footprint,
    add_switch_footprint,
    equal_ignore_order,
    generate_render,
    update_netinfo,
)


def get_board_with_one_switch(
    request, footprint: str, number_of_diodes: int = 1
) -> Tuple[pcbnew.BOARD, pcbnew.FOOTPRINT, List[pcbnew.FOOTPRINT]]:
    board = pcbnew.CreateEmptyBoard()
    net_count = board.GetNetCount()

    def _add_net(name: str, netcode: int) -> pcbnew.NETINFO_ITEM:
        net = pcbnew.NETINFO_ITEM(board, name, netcode)
        update_netinfo(board, net)
        board.Add(net)
        return net

    switch_diode_net = _add_net("Net-(D-Pad2)", net_count)
    column_net = _add_net("COL1", net_count + 1)
    row_net = _add_net("ROW1", net_count + 2)

    switch = add_switch_footprint(board, request, 1, footprint=footprint)
    for p in switch.Pads():
        if p.GetNumber() == "2":
            p.SetNet(switch_diode_net)

    diodes = []
    for i in range(number_of_diodes):
        diode = add_diode_footprint(board, request, i + 1)
        diode.FindPadByNumber("1").SetNet(row_net)
        diode.FindPadByNumber("2").SetNet(switch_diode_net)
        diodes.append(diode)

    for p in switch.Pads():
        if p.GetNumber() == "1":
            p.SetNet(column_net)

    return board, switch, diodes


def save_and_render(board: pcbnew.BOARD, tmpdir, request) -> None:
    pcb_path = f"{tmpdir}/test.kicad_pcb"
    board.Save(pcb_path)
    generate_render(request, pcb_path)


def assert_board_tracks(
    expected: list[Tuple[int, int]] | None, board: pcbnew.BOARD
) -> None:
    expected_points = [pcbnew.VECTOR2I(*x) for x in expected] if expected else None
    points = []
    for track in board.GetTracks():
        start = track.GetStart()
        if start not in points:
            points.append(start)
        end = track.GetEnd()
        if end not in points:
            points.append(end)

    if expected_points:
        assert equal_ignore_order(points, expected_points)
    else:
        assert not points


@pytest.mark.parametrize(
    "position,orientation,expected",
    [
        # fmt: off
        # simple cases when pads in line, expecting single segment track:
        ((-4,  0),   0, [(-410000, -5080000), (2540000, -5080000)]),
        (( 0,  4),  90, [(2540000, -2130000), (2540000, -5080000)]),
        (( 4,  0), 180, [(5490000, -5080000), (2540000, -5080000)]),
        (( 0, -4), 270, [(2540000, -8030000), (2540000, -5080000)]),
        # cases where need to route with two segment track:
        ((-4,  1),   0, [(-410000,  -4080000), (590000,   -5080000), (2540000, -5080000)]),
        ((-4, -1),   0, [(-410000,  -6080000), (590000,   -5080000), (2540000, -5080000)]),
        ((-4,  1),  90, [(-1460000, -5130000), (-1410000, -5080000), (2540000, -5080000)]),
        ((-4, -1),  90, [(-1460000, -7130000), (590000,   -5080000), (2540000, -5080000)]),
        ((-4,  1), 180, [(-2510000, -4080000), (-1510000, -5080000), (2540000, -5080000)]),
        ((-4, -1), 180, [(-2510000, -6080000), (-1510000, -5080000), (2540000, -5080000)]),
        ((-4,  1), 270, [(-1460000, -3030000), (590000,   -5080000), (2540000, -5080000)]),
        ((-4, -1), 270, [(-1460000, -5030000), (-1410000, -5080000), (2540000, -5080000)]),
        (( 1, 10),   0, [(4590000,   4920000), (2540000,   2870000), (2540000, -5080000)]),
        ((-1, 10),   0, [(2590000,   4920000), (2540000,   4870000), (2540000, -5080000)]),
        (( 1, 10),  90, [(3540000,   3870000), (2540000,   2870000), (2540000, -5080000)]),
        ((-1, 10),  90, [(1540000,   3870000), (2540000,   2870000), (2540000, -5080000)]),
        (( 1, 10), 180, [(2490000,   4920000), (2540000,   4870000), (2540000, -5080000)]),
        ((-1, 10), 180, [(490000,    4920000), (2540000,   2870000), (2540000, -5080000)]),
        (( 1, 10), 270, [(3540000,   5970000), (2540000,   4970000), (2540000, -5080000)]),
        ((-1, 10), 270, [(1540000,   5970000), (2540000,   4970000), (2540000, -5080000)]),
        (( 4,  1),   0, [(7590000,  -4080000), (6590000,  -5080000), (2540000, -5080000)]),
        (( 4, -1),   0, [(7590000,  -6080000), (6590000,  -5080000), (2540000, -5080000)]),
        (( 4,  1),  90, [(6540000,  -5130000), (6490000,  -5080000), (2540000, -5080000)]),
        (( 4, -1),  90, [(6540000,  -7130000), (4490000,  -5080000), (2540000, -5080000)]),
        (( 4,  1), 180, [(5490000,  -4080000), (4490000,  -5080000), (2540000, -5080000)]),
        (( 4, -1), 180, [(5490000,  -6080000), (4490000,  -5080000), (2540000, -5080000)]),
        (( 4,  1), 270, [(6540000,  -3030000), (4490000,  -5080000), (2540000, -5080000)]),
        (( 4, -1), 270, [(6540000,  -5030000), (6490000,  -5080000), (2540000, -5080000)]),
        (( 1, -4),   0, [(4590000,  -9080000), (2540000,  -7030000), (2540000, -5080000)]),
        ((-1, -4),   0, [(2590000,  -9080000), (2540000,  -9030000), (2540000, -5080000)]),
        (( 1, -4),  90, [(3540000, -10130000), (2540000,  -9130000), (2540000, -5080000)]),
        ((-1, -4),  90, [(1540000, -10130000), (2540000,  -9130000), (2540000, -5080000)]),
        (( 1, -4), 180, [(2490000,  -9080000), (2540000,  -9030000), (2540000, -5080000)]),
        ((-1, -4), 180, [(490000,   -9080000), (2540000,  -7030000), (2540000, -5080000)]),
        (( 1, -4), 270, [(3540000,  -8030000), (2540000,  -7030000), (2540000, -5080000)]),
        ((-1, -4), 270, [(1540000,  -8030000), (2540000,  -7030000), (2540000, -5080000)]),
        # these positions used to be difficult for router but works after adding second
        # attempt with track posture changed, if the first try failed:
        ((5.5, 5),  90, [(8040000,  -1130000), (4090000,  -5080000), (2540000, -5080000)]),
        ((7, 10),   90, [(9540000,   3870000), (9540000,   1920000), (2540000, -5080000)]),
        # special cases testing some edge cases or special conditions:
        # cases to difficult for router. Two segment track would collide with footprint:
        ((-7, 10), 90, None),
        # fmt: on
    ],
)
@pytest.mark.parametrize("side", [Side.FRONT, Side.BACK])
def test_diode_switch_routing(
    position, orientation, side, expected, tmpdir, request
) -> None:
    board, switch, diodes = get_board_with_one_switch(request, "SW_Cherry_MX_PCB_1.00u")
    key_placer = KeyPlacer(board)

    switch_pad = switch.FindPadByNumber("2")
    switch_pad_position = switch_pad.GetPosition()
    if KICAD_VERSION < (7, 0, 0):
        switch_pad_position = pcbnew.VECTOR2I(switch_pad_position)

    diode_position = switch_pad_position + pcbnew.VECTOR2I_MM(*position)
    set_position(diodes[0], diode_position)
    set_side(diodes[0], side)
    diodes[0].SetOrientationDegrees(orientation)

    key_placer.route_switch_with_diode(switch, diodes)
    key_placer.remove_dangling_tracks()

    save_and_render(board, tmpdir, request)
    assert_board_tracks(expected, board)


@pytest.mark.parametrize(
    "position,orientation,expected",
    [
        # fmt: off
        # simple cases when pads in line, expecting single segment track:
        ((0,  3.8),  0, [(1050000,  3800000), ( 5000000, 3800000)]),
        ((-8, 3.8),  0, [(-6950000, 3800000), (-5000000, 3800000)]),
        # fmt: on
    ],
)
def test_diode_switch_routing_complicated_footprint(
    position, orientation, expected, tmpdir, request
) -> None:
    board, switch, diodes = get_board_with_one_switch(
        request, "Kailh_socket_PG1350_optional_reversible"
    )
    key_placer = KeyPlacer(board)

    set_position(diodes[0], pcbnew.VECTOR2I_MM(*position))
    diodes[0].SetOrientationDegrees(orientation)

    key_placer.route_switch_with_diode(switch, diodes)

    save_and_render(board, tmpdir, request)
    assert_board_tracks(expected, board)


def test_multi_diode_switch_routing(tmpdir, request) -> None:
    board, switch, diodes = get_board_with_one_switch(
        request, "SW_Cherry_MX_PCB_1.00u", number_of_diodes=2
    )
    key_placer = KeyPlacer(board)
    diode_positions = [(0, 5), (0, -10)]
    for position, diode in zip(diode_positions, diodes):
        set_position(diode, pcbnew.VECTOR2I_MM(*position))
        diode.SetOrientationDegrees(0)
    key_placer.route_switch_with_diode(switch, diodes)

    save_and_render(board, tmpdir, request)

    expected = [
        (2540000, -8510000),
        (1050000, -10000000),
        (2540000, -5080000),
        (2540000, 3510000),
        (1050000, 5000000),
    ]
    assert_board_tracks(expected, board)


def test_diode_switch_routing_not_matching_nets(tmpdir, request, caplog) -> None:
    board, switch, diodes = get_board_with_one_switch(request, "SW_Cherry_MX_PCB_1.00u")
    key_placer = KeyPlacer(board)

    assert len(diodes) == 1
    diodes[0].FindPadByNumber("2").SetNet(None)
    set_position(diodes[0], pcbnew.VECTOR2I_MM(0, 5))

    with caplog.at_level(logging.ERROR):
        key_placer.route_switch_with_diode(switch, diodes)
    save_and_render(board, tmpdir, request)

    assert "Could not find pads with the same net, routing skipped" in caplog.text
    assert_board_tracks([], board)


def test_multi_diode_illegal_position_setting(request) -> None:
    board, _, _ = get_board_with_one_switch(
        request, "SW_Cherry_MX_PCB_1.00u", number_of_diodes=2
    )
    key_placer = KeyPlacer(board)

    with pytest.raises(
        PluginError,
        match=r"The 'Custom' position not supported for multiple diodes per switch",
    ):
        key_placer.run(
            "",  # not important, should raise even when layout not provided
            ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, ""),
            ElementInfo("D{}", PositionOption.CUSTOM, ZERO_POSITION, ""),
        )


def get_2x2_layout_path(request) -> str:
    return f"{request.fspath.dirname}/../examples/2x2/kle-internal.json"


def add_2x2_nets(board):
    net_count = board.GetNetCount()
    for i, n in enumerate(
        [
            "COL0",
            "COL1",
            "ROW0",
            "ROW1",
            "Net-D1-Pad2",
            "Net-D2-Pad2",
            "Net-D3-Pad2",
            "Net-D4-Pad2",
        ]
    ):
        net = pcbnew.NETINFO_ITEM(board, n, net_count + i)
        update_netinfo(board, net)
        board.Add(net)
    return board.GetNetInfo().NetsByName()


def get_board_for_2x2_example(request) -> pcbnew.BOARD:
    board = pcbnew.CreateEmptyBoard()
    netcodes_map = add_2x2_nets(board)
    for i in range(1, 5):
        switch = add_switch_footprint(board, request, i)
        switch.FindPadByNumber("1").SetNet(netcodes_map[f"COL{(i - 1) & 0x01}"])
        switch.FindPadByNumber("2").SetNet(netcodes_map[f"Net-D{i}-Pad2"])
        diode = add_diode_footprint(board, request, i)
        diode.FindPadByNumber("1").SetNet(netcodes_map[f"ROW{i // 3}"])
        diode.FindPadByNumber("2").SetNet(netcodes_map[f"Net-D{i}-Pad2"])
    return board


def assert_2x2_layout_switches(
    board: pcbnew.BOARD, key_distance: Tuple[float, float]
) -> None:
    switches = [get_footprint(board, f"SW{i}") for i in range(1, 5)]
    positions = [get_position(switch) for switch in switches]
    assert positions[0] == pcbnew.VECTOR2I_MM(key_distance[0] * 2, key_distance[1] * 2)
    assert positions[1] - positions[0] == pcbnew.VECTOR2I_MM(key_distance[0], 0)
    assert positions[2] - positions[0] == pcbnew.VECTOR2I_MM(0, key_distance[1])
    assert positions[3] - positions[2] == pcbnew.VECTOR2I_MM(key_distance[0], 0)
    assert positions[3] - positions[1] == pcbnew.VECTOR2I_MM(0, key_distance[1])


@pytest.mark.parametrize(
    "key_distance",
    [
        (0, 0),
        (10, 10),
        (19, 19),
        (19.05, 19.05),
        (22.222, 22.222),
        (0, 10),
        (10, 0),
        (18, 17),
        (18, 19),
    ],
)
def test_switch_distance(key_distance, tmpdir, request) -> None:
    board = get_board_for_2x2_example(request)
    key_placer = KeyPlacer(board, key_distance)
    diode_position = DEFAULT_DIODE_POSITION
    key_placer.run(
        get_2x2_layout_path(request),
        ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, ""),
        ElementInfo("D{}", PositionOption.DEFAULT, diode_position, ""),
        True,
    )

    save_and_render(board, tmpdir, request)

    assert_2x2_layout_switches(board, key_distance)
    switches = [get_footprint(board, f"SW{i}") for i in range(1, 5)]
    diodes = [get_footprint(board, f"D{i}") for i in range(1, 5)]
    for switch, diode in zip(switches, diodes):
        x, y = diode_position.x, diode_position.y
        assert get_position(diode) == get_position(switch) + pcbnew.VECTOR2I_MM(x, y)


def test_diode_placement_ignore(tmpdir, request) -> None:
    board = get_board_for_2x2_example(request)
    key_placer = KeyPlacer(board)
    key_info = ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "")
    diode_info = ElementInfo(
        "D{}", PositionOption.UNCHANGED, DEFAULT_DIODE_POSITION, ""
    )
    key_placer.run(get_2x2_layout_path(request), key_info, diode_info, False)

    save_and_render(board, tmpdir, request)

    assert_2x2_layout_switches(board, (19.05, 19.05))
    diodes = [get_footprint(board, f"D{i}") for i in range(1, 5)]
    positions = [get_position(diode) for diode in diodes]
    for pos in positions:
        assert pos == pcbnew.VECTOR2I(0, 0)
    # running without routing enabled, 'router' is not that good yet to correctly
    # handle illegal (overlapping) diodes
    assert len(board.GetTracks()) == 0


def test_placer_invalid_layout(tmpdir, request) -> None:
    board = get_board_for_2x2_example(request)
    key_placer = KeyPlacer(board)
    key_info = ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "")
    diode_info = ElementInfo("D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, "")

    layout_path = f"{tmpdir}/kle.json"
    with open(layout_path, "w") as f:
        json.dump({"some": "urecognized layout format"}, f)

    with pytest.raises(RuntimeError):
        key_placer.run(layout_path, key_info, diode_info, True)


def test_switch_iterator_default_mode(request) -> None:
    board = get_board_for_2x2_example(request)
    key_matrix = KeyMatrix(board, "SW{}", "D{}")
    with open(get_2x2_layout_path(request), "r") as f:
        layout = json.load(f)
        keyboard = get_keyboard(layout)

    iterator = KeyboardSwitchIterator(keyboard, key_matrix)
    expected_keys = iter(keyboard.keys)
    expected_footprints = iter(["SW1", "SW2", "SW3", "SW4"])
    for key, footprint in iterator:
        assert key == next(expected_keys)
        assert footprint.GetReference() == next(expected_footprints)


def test_switch_iterator_explicit_annotation_mode(request) -> None:
    board = get_board_for_2x2_example(request)
    key_matrix = KeyMatrix(board, "SW{}", "D{}")
    with open(get_2x2_layout_path(request), "r") as f:
        layout = json.load(f)
        keyboard = get_keyboard(layout)
    expected_order = ["3", "1", "4", "2"]
    for i, k in enumerate(keyboard.keys):
        k.set_label(KeyboardSwitchIterator.EXPLICIT_ANNOTATION_LABEL, expected_order[i])
    iterator = KeyboardSwitchIterator(keyboard, key_matrix)
    expected_keys = iter(keyboard.keys)
    expected_footprints = iter([f"SW{i}" for i in expected_order])
    for key, footprint in iterator:
        assert key == next(expected_keys)
        assert footprint.GetReference() == next(expected_footprints)


def test_switch_iterator_default_mode_ignore_decal(request) -> None:
    board = get_board_for_2x2_example(request)
    key_matrix = KeyMatrix(board, "SW{}", "D{}")
    with open(get_2x2_layout_path(request), "r") as f:
        layout = json.load(f)
        # add some decal keys
        for key in list(layout["keys"]):
            k = copy.copy(key)
            k["decal"] = True
            layout["keys"].append(k)
        keyboard = get_keyboard(layout)

    iterator = KeyboardSwitchIterator(keyboard, key_matrix)
    expected_keys = iter(keyboard.keys[0:4])
    expected_footprints = iter(["SW1", "SW2", "SW3", "SW4"])
    for key, footprint in iterator:
        assert key == next(expected_keys)
        assert footprint.GetReference() == next(expected_footprints)


def test_placer_board_without_matching_switches(request) -> None:
    board = get_board_for_2x2_example(request)
    key_placer = KeyPlacer(board)
    key_info = ElementInfo("MX{}", PositionOption.DEFAULT, ZERO_POSITION, "")
    diode_info = ElementInfo("D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, "")
    layout_path = get_2x2_layout_path(request)

    with pytest.raises(
        PluginError, match=r"No switch footprints found using 'MX{}' annotation format"
    ):
        key_placer.run(layout_path, key_info, diode_info, True)


def test_placing_additional_elements(tmpdir, request) -> None:
    """Tests if placer correctly applies RELATIVE position
    for each 'additional element'
    """
    board = get_board_for_2x2_example(request)
    key_placer = KeyPlacer(board)
    key_info = ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "")
    diode_info = ElementInfo("D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, "")
    additional_elements = [ElementInfo("LED{}", PositionOption.RELATIVE, None, "")]
    layout_path = get_2x2_layout_path(request)

    for i in range(1, 5):
        led = add_led_footprint(board, request, i)
        if i % 2 == 0:
            set_side(led, Side.BACK)
        set_rotation(led, 10 * (i - 1))

    sw1 = get_footprint(board, "SW1")
    led1 = get_footprint(board, "LED1")

    position_offset = pcbnew.VECTOR2I_MM(0, 5)
    set_position(led1, get_position(sw1) + position_offset)

    key_placer.run(layout_path, key_info, diode_info, True, True, additional_elements)

    save_and_render(board, tmpdir, request)

    assert_2x2_layout_switches(board, (19.05, 19.05))

    switches = [get_footprint(board, f"SW{i}") for i in range(1, 5)]
    leds = [get_footprint(board, f"LED{i}") for i in range(1, 5)]
    for switch, led in zip(switches, leds):
        assert get_position(led) == get_position(switch) + position_offset
        # because reference LED1 is on front side and rotated by 0 degrees:
        assert get_side(led) == Side.FRONT
        assert get_orientation(led) == 0


def test_placing_additional_elements_for_alternative_keys(tmpdir, request) -> None:
    """Tests if placer correctly differentiate between additional elements
    for alternative layouts keys in case of matrix annotated layouts.
    Common case includes bottom row with various layouts, where alternative keys
    can have different width stabilizers.
    This also tests for old bug where ST43 was placed next to SW43_1 instead of SW43.
    """
    board = pcbnew.CreateEmptyBoard()
    ref_values = ["0", "0_1", "0_2", "1"]  # first key with two alternatives
    for i in range(0, 4):
        switch = add_switch_footprint(board, request, ref_values[i])
        # skipping nets, would raise error message in log but tested operation should
        # succeed anyway
        position_offset = pcbnew.VECTOR2I_MM(20 * i, 0)
        set_position(switch, pcbnew.VECTOR2I_MM(0, 0) + position_offset)

    destination = "0_2"
    # not using real stabilizer footprint but that's not important here
    # interested in resulting position
    stab = add_led_footprint(board, request, destination)

    key_placer = KeyPlacer(board)
    key_info = ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "")
    diode_info = ElementInfo("", PositionOption.DEFAULT, ZERO_POSITION, "")
    additional_elements = [
        ElementInfo("LED{}", PositionOption.CUSTOM, ZERO_POSITION, "")
    ]

    key_placer.run("", key_info, diode_info, False, False, additional_elements)

    save_and_render(board, tmpdir, request)

    assert get_position(stab) == pcbnew.VECTOR2I_MM(
        20 * ref_values.index(destination), 0
    )


def test_placer_diode_from_preset_missing_path(request) -> None:
    board = get_board_for_2x2_example(request)
    key_placer = KeyPlacer(board)
    key_info = ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "")
    diode_info = ElementInfo("D{}", PositionOption.PRESET, None, "")
    layout_path = get_2x2_layout_path(request)

    with pytest.raises(PluginError, match=r"Template path can't be empty"):
        key_placer.run(layout_path, key_info, diode_info, True)


def test_placer_diode_from_illegal_preset(tmpdir, request) -> None:
    template_path = f"{tmpdir}/template.kicad_pcb"
    board = get_board_for_2x2_example(request)
    key_placer = KeyPlacer(board)
    key_info = ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "")
    diode_info = ElementInfo("D{}", PositionOption.PRESET, None, template_path)
    layout_path = get_2x2_layout_path(request)

    template, _, _ = get_board_with_one_switch(request, "SW_Cherry_MX_PCB_1.00u")
    # having two switches in template file makes it illegal:
    add_switch_footprint(template, request, 2)

    template.Save(template_path)

    with pytest.raises(
        PluginError,
        match=(
            r"Template file '.*' must have exactly one switch. "
            "Found 2 switches using 'SW{}' annotation format."
        ),
    ):
        key_placer.run(layout_path, key_info, diode_info, True)

    save_and_render(board, tmpdir, request)


def get_board_for_2x2_without_diodes_example(request) -> pcbnew.BOARD:
    board = get_board_for_2x2_example(request)
    netcodes_map = board.GetNetInfo().NetsByNetcode()

    for f in board.GetFootprints():
        ref = f.GetReference()
        if ref.startswith("D"):
            board.RemoveNative(f)
        elif ref.startswith("SW"):
            sw_pad = f.FindPadByNumber("2")
            sw_pad.SetNet(netcodes_map[0])
    return board


def test_placer_no_diodes(tmpdir, request) -> None:
    """Tests if placing switches works when diodes can't be found.
    This can be intentional when using direct-pin switch connections
    (there is no matrix, each switch is connected directed to MCU).
    For such PCBs placer should still work as long as layout file is not
    via-annotated (row/column assignments makes no sense for direct-pin).
    QMK solves that by creating virtual key matrix, but for that we
    would need to define switch mcu nets to virtual row/key mapping.
    """
    board = get_board_for_2x2_without_diodes_example(request)
    key_info = ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "")
    diode_info = ElementInfo("", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, "")
    layout_path = f"{request.fspath.dirname}/../examples/2x2/kle.json"

    key_placer = KeyPlacer(board)
    # enable routing, we expect that no tracks are added
    key_placer.run(layout_path, key_info, diode_info, route_rows_and_columns=True)

    save_and_render(board, tmpdir, request)

    assert_2x2_layout_switches(board, (19.05, 19.05))
    assert len(board.GetTracks()) == 0


def test_placer_no_diodes_via_annotated_layout(tmpdir, request) -> None:
    """If via-annotated layout detected and no diodes,
    best we can do is raise clear error message with suggestion to use
    implicit annotations.
    """
    board = get_board_for_2x2_without_diodes_example(request)
    key_info = ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, "")
    diode_info = ElementInfo("", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, "")
    layout_path = f"{request.fspath.dirname}/../examples/2x2/kle-annotated.json"

    key_placer = KeyPlacer(board)

    with pytest.raises(
        PluginError,
        match=(
            "Detected layout file with via-annotated matrix positions "
            "while not all footprints on PCB can be unambiguously associated "
            "with row/column position."
        ),
    ):
        key_placer.run(layout_path, key_info, diode_info, route_rows_and_columns=True)

    switches = [get_footprint(board, f"SW{i}") for i in range(1, 5)]
    for sw in switches:
        assert sw.GetPosition() == pcbnew.VECTOR2I(0, 0)
    assert len(board.GetTracks()) == 0

    save_and_render(board, tmpdir, request)
