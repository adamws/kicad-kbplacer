# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import collections
import json
import math
import re
import subprocess
from pathlib import Path

import pcbnew
import pytest
import sexpdata

from kbplacer.design_block import (
    BUNDLED_LIBRARY,
    DesignBlock,
    PresetBoardPlacer,
    PresetInstance,
    PresetSpec,
    allocate_references,
    block_side,
    bundled_presets,
    matrix_net_names,
    plan_presets,
)
from kbplacer.element_position import ElementInfo, PositionOption, Side
from kbplacer.kbplacer_plugin import PluginSettings, run_board, run_schematic
from kbplacer.kle_serial import MatrixAnnotatedKeyboard, get_keyboard

from .conftest import (
    KICAD_VERSION,
    generate_netlist,
    kicad_cli,
    run_schematic_parity_drc,
)

LIBRARY = Path(__file__).parent.parent / "kbplacer/presets/kbplacer.kicad_blocks"
MCU_V1 = f"{LIBRARY}:mcu_atmega32u4_v1"
MCU_V2 = f"{LIBRARY}:mcu_atmega32u4_v2"
USB_BLOCKS = [f"{LIBRARY}:usb_minimal", f"{LIBRARY}:usb_udb_clone"]
# pins exposed with `GPIO<n>` labels by the ATmega32U4 blocks
ATMEGA_GPIO_COUNT = 25

LAYOUT = [["0,0", "0,1"], ["1,0", "1,1"]]

requires_kicad_10 = pytest.mark.skipif(
    KICAD_VERSION < (10, 0, 0), reason="Design blocks are saved with KiCad 10"
)


def _keyboard(layout=LAYOUT) -> MatrixAnnotatedKeyboard:
    return MatrixAnnotatedKeyboard.from_keyboard(get_keyboard(layout))


def _grid_layout(rows: int, columns: int) -> list:
    return [[f"{r},{c}" for c in range(columns)] for r in range(rows)]


@pytest.fixture
def aux_block(tmpdir) -> str:
    """Copy of an ATmega32U4 block without GPIO labels, i.e. a preset which
    does not drive the key matrix but uses the very same references."""
    source = LIBRARY / "mcu_atmega32u4_v2.kicad_block"
    library = Path(tmpdir) / "aux.kicad_blocks"
    destination = library / "aux.kicad_block"
    destination.mkdir(parents=True)
    for suffix in (".kicad_sch", ".kicad_pcb", ".json"):
        text = (source / f"{source.stem}{suffix}").read_text()
        text = re.sub(r"\bGPIO(\d+)\b", r"SPARE\1", text)
        (destination / f"aux{suffix}").write_text(text)
    return f"{library}:aux"


class TestDesignBlockIdentifier:
    def test_library_identifier(self) -> None:
        block = DesignBlock.from_identifier(MCU_V1)
        assert block.name == "mcu_atmega32u4_v1"
        assert block.schematic_path.name == "mcu_atmega32u4_v1.kicad_sch"
        assert block.pcb_path.name == "mcu_atmega32u4_v1.kicad_pcb"

    def test_directory_identifier(self) -> None:
        block = DesignBlock.from_identifier(
            str(LIBRARY / "mcu_atmega32u4_v2.kicad_block")
        )
        assert block.name == "mcu_atmega32u4_v2"

    def test_missing_block(self) -> None:
        with pytest.raises(ValueError, match="not found in library"):
            DesignBlock.from_identifier(f"{LIBRARY}:does_not_exist")

    def test_bundled_identifier(self) -> None:
        assert BUNDLED_LIBRARY == LIBRARY
        block = DesignBlock.from_identifier("usb_minimal")
        assert block.directory == LIBRARY / "usb_minimal.kicad_block"
        assert block.description.startswith("USB-C receptacle")

    def test_missing_bundled_block(self) -> None:
        with pytest.raises(ValueError, match=r"nor a bundled preset \(available: mcu"):
            DesignBlock.from_identifier("does_not_exist")

    def test_bundled_presets(self) -> None:
        assert bundled_presets() == [
            "mcu_atmega32u4_v1",
            "mcu_atmega32u4_v2",
            "usb_minimal",
            "usb_udb_clone",
        ]

    @pytest.mark.parametrize(
        "identifier",
        ["no_such_block", "relative/no_such_block", "/some/library.pretty:mcu"]
        + [f"{LIBRARY}:"],
    )
    def test_invalid_identifier(self, identifier) -> None:
        with pytest.raises(ValueError):
            DesignBlock.from_identifier(identifier)


class TestAllocateReferences:
    def test_renumbers_after_taken(self) -> None:
        taken = {"C": 4, "SW": 4}
        mapping = allocate_references(["C2", "C1", "U1", "C10"], taken)
        # relative order kept, numbering continues after the taken ones
        assert mapping == {"C1": "C5", "C2": "C6", "C10": "C7", "U1": "U1"}
        assert taken == {"C": 7, "SW": 4, "U": 1}

    def test_successive_calls_never_collide(self) -> None:
        taken = {}
        first = allocate_references(["U1", "C1"], taken)
        second = allocate_references(["U1", "C1"], taken)
        assert first == {"U1": "U1", "C1": "C1"}
        assert second == {"U1": "U2", "C1": "C2"}

    @pytest.mark.parametrize("reference", ["C?", "REF**"])
    def test_rejects_unannotated(self, reference) -> None:
        with pytest.raises(ValueError, match="unannotated"):
            allocate_references([reference], {}, block_name="test")


class TestPlanPresets:
    def test_matrix_net_names_rows_first(self) -> None:
        keyboard = _keyboard(_grid_layout(2, 11))
        names = matrix_net_names(keyboard)
        assert names[:3] == ["ROW0", "ROW1", "COL0"]
        # natural, not lexicographic, sort
        assert names[-2:] == ["COL9", "COL10"]

    def test_default_gpio_order(self) -> None:
        (preset,) = plan_presets([PresetSpec(MCU_V1)], _keyboard())
        assert preset.nets == {
            "GPIO0": "ROW0",
            "GPIO1": "ROW1",
            "GPIO2": "COL0",
            "GPIO3": "COL1",
        }
        assert preset.sheet_name == "mcu_atmega32u4_v1"

    def test_custom_pin_order(self) -> None:
        order = ["GPIO24", "GPIO7", "GPIO0", "GPIO1"]
        (preset,) = plan_presets(
            [PresetSpec(MCU_V1)], _keyboard(), matrix_pin_order=order
        )
        assert preset.nets == dict(zip(order, ["ROW0", "ROW1", "COL0", "COL1"]))

    def test_custom_pin_order_unknown_label(self) -> None:
        with pytest.raises(ValueError, match="not present"):
            plan_presets([PresetSpec(MCU_V1)], _keyboard(), matrix_pin_order=["GPIO99"])

    def test_not_enough_pins(self) -> None:
        keyboard = _keyboard(_grid_layout(13, ATMEGA_GPIO_COUNT - 12))
        with pytest.raises(ValueError, match="provides only 25"):
            plan_presets([PresetSpec(MCU_V1)], keyboard)

    def test_largest_matrix_which_fits(self) -> None:
        keyboard = _keyboard(_grid_layout(12, ATMEGA_GPIO_COUNT - 12))
        (preset,) = plan_presets([PresetSpec(MCU_V1)], keyboard)
        assert len(preset.nets) == ATMEGA_GPIO_COUNT

    def test_single_matrix_controller(self) -> None:
        with pytest.raises(ValueError, match="Only one preset"):
            plan_presets([PresetSpec(MCU_V1), PresetSpec(MCU_V2)], _keyboard())

    @pytest.mark.parametrize(
        "with_leds,with_led_capacitors,first_capacitor",
        [(False, False, "C1"), (True, False, "C1"), (True, True, "C5")],
    )
    def test_references_skip_generated_ones(
        self, with_leds, with_led_capacitors, first_capacitor
    ) -> None:
        (preset,) = plan_presets(
            [PresetSpec(MCU_V1)],
            _keyboard(),
            with_leds=with_leds,
            with_led_capacitors=with_led_capacitors,
        )
        assert preset.references["C1"] == first_capacitor
        assert preset.references["U1"] == "U1"

    def test_multiple_presets(self, aux_block) -> None:
        presets = plan_presets(
            [PresetSpec(MCU_V1), PresetSpec(aux_block), PresetSpec(aux_block)],
            _keyboard(),
        )
        assert [p.sheet_name for p in presets] == [
            "mcu_atmega32u4_v1",
            "aux",
            "aux_2",
        ]
        assert [p.references["U1"] for p in presets] == ["U1", "U2", "U3"]
        assert [p.references["C8"] for p in presets] == ["C8", "C16", "C24"]
        assert presets[1].nets == {}
        all_references = [r for p in presets for r in p.references.values()]
        assert len(all_references) == len(set(all_references))

    def test_pcb_net_names(self) -> None:
        preset = PresetInstance(
            block=DesignBlock.from_identifier(MCU_V1),
            sheet_name="mcu",
            position=None,
            references={"U1": "U2", "BTN1": "BTN1"},
            nets={"GPIO0": "ROW0"},
        )
        assert preset.pcb_net_name("GPIO0") == "ROW0"
        assert preset.pcb_net_name("GPIO1") == "GPIO1"
        assert preset.pcb_net_name("Net-(U1-UCAP)") == "Net-(U2-UCAP)"
        assert (
            preset.pcb_net_name("unconnected-(U1-AREF-Pad42)")
            == "unconnected-(U2-AREF-Pad42)"
        )
        assert preset.pcb_net_name("/XTAL1") == "/mcu/XTAL1"
        assert preset.pcb_net_name("MCU_D+") == "MCU_D+"
        assert preset.pcb_net_name("") == ""


def _settings(tmpdir, layout_path, presets, strategy) -> PluginSettings:
    footprints = get_footprints_dir_path()
    return PluginSettings(
        pcb_file_path=f"{tmpdir}/keyboard.kicad_pcb",
        layout_path=str(layout_path),
        key_info=ElementInfo("SW{}", PositionOption.DEFAULT, None, "", start_index=1),
        key_distance=None,
        diode_info=ElementInfo("D{}", PositionOption.DEFAULT, None, ""),
        route_switches_with_diodes=False,
        optimize_diodes_orientation=False,
        route_rows_and_columns=False,
        additional_elements=[],
        generate_outline=False,
        outline_delta=0.0,
        template_path="",
        create_pcb_file=True,
        create_sch_file=True,
        sch_file_path="",
        switch_footprint=f"{footprints}:SW_Cherry_MX_PCB_1.00u",
        diode_footprint=f"{footprints}:D_SOD-323",
        stabilizer_footprint="",
        project_path=f"{tmpdir}/keyboard.kicad_pro",
        bundle_strategy=strategy,
        presets=presets,
    )


def get_footprints_dir_path() -> Path:
    return Path(__file__).parent / "data/footprints/tests.pretty"


def _netlist_nets(netlist_path) -> dict:
    """Net name -> set of (reference, pin) nodes."""
    with open(netlist_path, "r") as f:
        netlist = sexpdata.load(f)

    def children(node, name):
        return [
            c
            for c in node
            if isinstance(c, list) and c and c[0] == sexpdata.Symbol(name)
        ]

    nets = {}
    for net in children(children(netlist, "nets")[0], "net"):
        name = children(net, "name")[0][1]
        nodes = set()
        for node in children(net, "node"):
            fields = {f[0].value(): f[1] for f in node[1:]}
            nodes.add((fields["ref"], fields["pin"]))
        nets[name] = nodes
    return nets


def _board_nets(board: pcbnew.BOARD) -> dict:
    nets = collections.defaultdict(set)
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            if pad.GetNetname():
                nets[pad.GetNetname()].add((footprint.GetReference(), pad.GetNumber()))
    return dict(nets)


def _place_preset(tmpdir, side, rotation=0.0) -> pcbnew.BOARD:
    (instance,) = plan_presets(
        [PresetSpec(MCU_V1, position=(100, 50, rotation), side=side)], _keyboard()
    )
    board = pcbnew.CreateEmptyBoard()
    PresetBoardPlacer(board).add(instance)
    path = Path(tmpdir) / f"{side}-{rotation}.kicad_pcb"
    pcbnew.SaveBoard(str(path), board)
    board.SetFileName(str(path))
    return board


def _unconnected_items(tmpdir, board: pcbnew.BOARD) -> int:
    report_path = Path(tmpdir) / "drc.json"
    subprocess.run(
        [
            kicad_cli(),
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            str(report_path),
            board.GetFileName(),
        ],
        check=False,
        capture_output=True,
    )
    return len(json.loads(report_path.read_text())["unconnected_items"])


@requires_kicad_10
@pytest.mark.parametrize("rotation", [0.0, 90.0])
def test_preset_side(tmpdir, rotation) -> None:
    designed = pcbnew.LoadBoard(str(DesignBlock.from_identifier(MCU_V1).pcb_path))
    assert block_side(designed) == Side.BACK

    kept = _place_preset(tmpdir, None, rotation)
    back = _place_preset(tmpdir, Side.BACK, rotation)
    front = _place_preset(tmpdir, Side.FRONT, rotation)

    def _footprints(board):
        return {
            f.GetReference(): (pcbnew.ToMM(f.GetPosition()), f.IsFlipped())
            for f in board.GetFootprints()
        }

    # requesting block's own side changes nothing
    assert _footprints(back) == _footprints(kept)
    assert block_side(back) == Side.BACK
    assert block_side(front) == Side.FRONT

    # flipped left to right around block origin, before rotation
    def _unrotate(position):
        # KiCad rotates counterclockwise on screen (y axis pointing down)
        x, y = position[0] - 100, position[1] - 50
        a = math.radians(rotation)
        return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)

    back_footprints = _footprints(back)
    for reference, (position, flipped) in _footprints(front).items():
        back_position, back_flipped = back_footprints[reference]
        assert flipped != back_flipped
        # in block coordinates, x offsets from block origin are mirrored
        x, y = _unrotate(position)
        back_x, back_y = _unrotate(back_position)
        assert (x, y) == pytest.approx((-back_x, back_y), abs=1e-4)
    assert front.FindFootprintByReference("U1").GetPosition() == pcbnew.VECTOR2I_MM(
        100, 50
    )

    # copper follows footprints to the other side and keeps connecting them
    def _layers(board):
        return collections.Counter(
            board.GetLayerName(t.GetLayer())
            for t in board.GetTracks()
            if not isinstance(t, pcbnew.PCB_VIA)
        )

    back_layers = _layers(back)
    assert _layers(front) == {
        "F.Cu": back_layers["B.Cu"],
        "B.Cu": back_layers["F.Cu"],
    }
    assert _board_nets(front) == _board_nets(back)
    assert _unconnected_items(tmpdir, front) == _unconnected_items(tmpdir, back)


@requires_kicad_10
@pytest.mark.parametrize("strategy", ["hierarchical", "flat"])
def test_presets_project(tmpdir, aux_block, strategy) -> None:
    layout_path = Path(tmpdir) / "layout.json"
    layout_path.write_text(json.dumps(LAYOUT))
    presets = plan_presets(
        [
            PresetSpec(MCU_V1, position=(100, 50, 90)),
            PresetSpec(aux_block),
        ],
        _keyboard(),
    )
    settings = _settings(tmpdir, layout_path, presets, strategy)

    run_schematic(settings)
    board = run_board(settings)
    pcbnew.SaveBoard(settings.pcb_file_path, board)

    files = sorted(p.name for p in Path(tmpdir).glob("*.kicad_sch"))
    if strategy == "hierarchical":
        assert files == [
            "keyboard-aux.kicad_sch",
            "keyboard-key-matrix.kicad_sch",
            "keyboard-mcu_atmega32u4_v1.kicad_sch",
            "keyboard.kicad_sch",
        ]
    else:
        # key matrix keeps its name, presets are ordered after it
        assert files == [
            "keyboard-aux.kicad_sch",
            "keyboard-mcu_atmega32u4_v1.kicad_sch",
            "keyboard.kicad_sch",
        ]
        project = json.loads(Path(settings.project_path).read_text())
        assert [s[1] for s in project["sheets"]] == [
            "Key Matrix",
            "mcu_atmega32u4_v1",
            "aux",
        ]

    # board: one group per preset, explicit and automatic placement
    groups = {g.GetName(): g for g in board.Groups()}
    assert set(groups) == {"mcu_atmega32u4_v1", "aux"}
    u1 = board.FindFootprintByReference("U1")
    assert pcbnew.ToMM(u1.GetPosition()) == pytest.approx((100, 50))
    keyboard_bottom = max(
        f.GetBoundingBox(False, False).GetBottom()
        for f in board.GetFootprints()
        if f.GetReference().startswith(("SW", "D"))
    )
    aux_top = min(
        f.GetBoundingBox(False, False).GetTop()
        for f in board.GetFootprints()
        if f.GetParentGroup() and f.GetParentGroup().GetName() == "aux"
    )
    assert aux_top > keyboard_bottom

    board_nets = _board_nets(board)
    # matrix connected to controller: PB0 (pad 8) is GPIO0 -> ROW0
    assert ("U1", "8") in board_nets["ROW0"]
    assert ("D1", "1") in board_nets["ROW0"]
    # internal nets of each preset are kept apart
    assert ("U1", "XTAL1") not in board_nets
    assert board_nets["/mcu_atmega32u4_v1/XTAL1"].isdisjoint(board_nets["/aux/XTAL1"])
    # all internal tracks follow renamed nets: no unconnected copper
    for track in board.GetTracks():
        assert track.GetNetname(), "track lost its net"

    if strategy == "flat":
        # KiCad CLI loads just first top-level sheet of a flat project,
        # netlist level checks are only possible for hierarchical projects
        assert all(not f.GetPath().AsString() for f in board.GetFootprints())
        return

    netlist_nets = _netlist_nets(
        generate_netlist(tmpdir, Path(tmpdir) / "keyboard.kicad_sch")
    )
    assert board_nets == {
        name: nodes
        for name, nodes in netlist_nets.items()
        if nodes and name in board_nets
    }
    assert set(board_nets) <= set(netlist_nets)

    report = run_schematic_parity_drc(tmpdir, settings.pcb_file_path)
    issues = [
        v
        for v in report["schematic_parity"]
        if v["type"] != "footprint_symbol_field_mismatch"
    ]
    assert issues == []


@requires_kicad_10
@pytest.mark.parametrize("usb", USB_BLOCKS)
def test_microcontroller_with_usb(tmpdir, usb) -> None:
    layout_path = Path(tmpdir) / "layout.json"
    layout_path.write_text(json.dumps(LAYOUT))
    mcu, usb_preset = plan_presets(
        [PresetSpec(MCU_V2, (100, 50, 0)), PresetSpec(usb, (100, 20, 0))],
        _keyboard(),
    )
    # both blocks use U1, `usb_udb_clone` D1 collides with matrix diodes
    # (checked below, all board references are unique)
    assert mcu.references["U1"] == "U1"
    assert usb_preset.references["U1"] == "U2"
    settings = _settings(tmpdir, layout_path, [mcu, usb_preset], "hierarchical")

    run_schematic(settings)
    board = run_board(settings)
    pcbnew.SaveBoard(settings.pcb_file_path, board)

    references = [f.GetReference() for f in board.GetFootprints()]
    assert len(references) == len(set(references))

    # USB data lines connect microcontroller series resistors with connector
    # (through ESD protection), with no other preset nets merged into them
    board_nets = _board_nets(board)
    resistors = {mcu.references["R1"], mcu.references["R2"]}
    for net in ["MCU_D+", "MCU_D-"]:
        nodes = board_nets[net]
        references = {r for r, _ in nodes}
        assert references & resistors
        assert "U2" in references
        # in `usb_minimal` connector is behind ESD protection (local nets)
        assert ("J1" in references) == usb.endswith("usb_udb_clone")

    netlist_nets = _netlist_nets(
        generate_netlist(tmpdir, Path(tmpdir) / "keyboard.kicad_sch")
    )
    assert board_nets == {
        name: nodes
        for name, nodes in netlist_nets.items()
        if nodes and name in board_nets
    }
    report = run_schematic_parity_drc(tmpdir, settings.pcb_file_path)
    issues = [
        v
        for v in report["schematic_parity"]
        if v["type"] != "footprint_symbol_field_mismatch"
    ]
    assert issues == []


@requires_kicad_10
def test_preset_power_references_follow_led_chain(tmpdir) -> None:
    layout_path = Path(tmpdir) / "layout.json"
    layout_path.write_text(json.dumps(LAYOUT))
    presets = plan_presets(
        [PresetSpec(MCU_V1)], _keyboard(), with_leds=True, with_led_capacitors=True
    )
    settings = _settings(tmpdir, layout_path, presets, "hierarchical")
    settings.create_pcb_file = False
    settings.pcb_file_path = ""
    settings.create_led_sch_file = True
    settings.led_footprint = (
        f"{get_footprints_dir_path()}:LED_SK6812MINI_PLCC4_3.5x3.5mm_P1.75mm"
    )
    settings.cap_footprint = f"{get_footprints_dir_path()}:C_0603_1608Metric"

    run_schematic(settings)

    nets = _netlist_nets(generate_netlist(tmpdir, Path(tmpdir) / "keyboard.kicad_sch"))
    references = [ref for nodes in nets.values() for ref, _ in nodes]
    assert "C4" in references and "C5" in references  # LED cap, preset cap
    text = "".join(p.read_text() for p in Path(tmpdir).glob("*.kicad_sch"))
    power = collections.Counter(re.findall(r'\(reference "(#PWR\d+)"\)', text))
    assert power and max(power.values()) == 1
    # contiguous: stale instance data of other projects kept in the block
    # file must not consume numbers
    numbers = sorted(int(r[len("#PWR") :]) for r in power)
    assert numbers == list(range(1, len(numbers) + 1))
