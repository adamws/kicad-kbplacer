# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
import shutil
import sys
import uuid
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import block2image  # noqa: E402

LIBRARY = TOOLS_DIR.parent / "kbplacer" / "presets" / "kbplacer.kicad_blocks"

requires_kicad_cli = pytest.mark.skipif(
    shutil.which("kicad-cli") is None, reason="kicad-cli not available"
)

SVG = """<?xml version="1.0" standalone="no"?>
<svg
  xmlns="http://www.w3.org/2000/svg"
  version="1.1"
  width="297.0022mm" height="210.0072mm" viewBox="0.0000 0.0000 297.0022 210.0072">
<title>SVG Image created as x.svg date 2026-11-10T13:16:47 </title>
<g style="fill:none;" transform="translate(0 0) scale(1 1)">
<path d="M 10.0000,20.0000
30.0000,20.0000
" />
<circle cx="40.0000" cy="25.0000" r="2.0000" />
<rect x="5.000000" y="22.000000" width="2.000000" height="10.000000" rx="0.000000" />
<path d="M30.0000 30.0000 A0.6350 0.6350 0.0 0 0 31.2700 30.0000" />
<text x="250.0000" y="200.0000" opacity="0">invisible</text>
</g>
</svg>
"""


def _view_box(svg: str):
    match = re.search(r'viewBox="([^"]*)"', svg)
    return [float(v) for v in match.group(1).split()]


def test_svg_content_bbox():
    assert block2image.svg_content_bbox(SVG) == (5.0, 20.0, 42.0, 32.0)


def test_crop_svg():
    svg, bbox = block2image.crop_svg(
        SVG, margin=1.0, scale=10.0, background="#123456", title="preview"
    )
    assert bbox == (5.0, 20.0, 42.0, 32.0)
    assert _view_box(svg) == [4.0, 19.0, 39.0, 14.0]
    assert 'width="390" height="140"' in svg
    background = '<rect x="4.0000" y="19.0000" width="39.0000" height="14.0000" '
    assert background + 'fill="#123456" />' in svg
    assert "<title>preview</title>" in svg
    assert "2026" not in svg


@pytest.mark.parametrize(
    "references,expected",
    [
        (["C1", "C2", "C3", "C5"], "C1-C3, C5"),
        (["R1"], "R1"),
        (["BTN1", "C1", "C2"], "BTN1, C1-C2"),
        (["X", "Y1", "Y2"], "X, Y1-Y2"),
    ],
)
def test_references_summary(references, expected):
    assert block2image._references_summary(references) == expected


def test_pcb_footprint_sides():
    pcb = (
        '(footprint "Lib:A"\n\t\t(layer "B.Cu")\n)'
        '(footprint "Lib:B" (layer "B.Cu"))'
        '(footprint "Lib:C"\n\t(layer "F.Cu"))'
    )
    sides = block2image.pcb_footprint_sides(pcb)
    assert sides["back"] == 2 and sides["front"] == 1


def test_find_blocks_rejects_other_paths(tmp_path):
    with pytest.raises(ValueError, match="neither design block"):
        block2image.find_blocks([str(tmp_path)])


def test_update_readme_keeps_hand_written_content(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Intro\n\n<!-- presets:begin -->\nstale\n<!-- presets:end -->\n\n# Outro\n"
    )
    block = block2image.BlockInfo(
        name="usb_c", directory=tmp_path / "lib.kicad_blocks" / "usb_c.kicad_block"
    )
    family = block2image.BlockFamily(name="usb_c", blocks=[block])
    block2image.update_readme(readme, [family])
    text = readme.read_text()
    assert text.startswith("# Intro\n\n<!-- presets:begin -->")
    assert text.endswith("<!-- presets:end -->\n\n# Outro\n")
    assert "stale" not in text
    assert "[usb_c](#usb_c)" in text
    assert "### usb_c" in text
    assert f"--preset {(tmp_path / 'lib.kicad_blocks').as_posix()}:usb_c" in text
    assert "none (no `GPIO<n>` labels)" in text

    # without markers, generated content is appended
    readme.write_text("# Intro\n")
    block2image.update_readme(readme, [family])
    text = readme.read_text()
    assert text.startswith("# Intro\n\n<!-- presets:begin -->")


def _block(tmp_path, name, schematic=None, description=""):
    directory = tmp_path / "lib.kicad_blocks" / f"{name}.kicad_block"
    directory.mkdir(parents=True)
    if schematic is not None:
        (directory / f"{name}.kicad_sch").write_text(schematic)
    return block2image.BlockInfo(
        name=name, directory=directory, description=description
    )


def test_group_variants(tmp_path):
    schematic = '(kicad_sch (uuid "{}") (symbol (lib_id "MCU:{}")))'
    blocks = [
        _block(tmp_path, "mcu_v2", schematic.format(uuid.uuid4(), "A")),
        _block(tmp_path, "mcu_v1", schematic.format(uuid.uuid4(), "A")),
        # same name base, different circuit
        _block(tmp_path, "mcu_v3", schematic.format(uuid.uuid4(), "B")),
        # same circuit, not a variant
        _block(tmp_path, "mcu", schematic.format(uuid.uuid4(), "A")),
        _block(tmp_path, "usb_v1", schematic.format(uuid.uuid4(), "C")),
    ]
    families = block2image.group_variants(blocks)
    assert [(f.name, [b.name for b in f.blocks]) for f in families] == [
        ("mcu", ["mcu_v1", "mcu_v2"]),
        ("mcu_v3", ["mcu_v3"]),
        ("mcu", ["mcu"]),
        ("usb_v1", ["usb_v1"]),
    ]


@pytest.mark.parametrize(
    "descriptions,expected",
    [
        (["A. B. C.", "A. B. D."], ("A. B.", ["C.", "D."])),
        (["A. C.", "B. C."], ("", ["A. C.", "B. C."])),
        (["A.", "A. D."], ("A.", ["", "D."])),
        (["", ""], ("", ["", ""])),
    ],
)
def test_split_descriptions(descriptions, expected):
    assert block2image.split_descriptions(descriptions) == expected


def test_variants_markdown(tmp_path):
    blocks = [
        _block(tmp_path, f"mcu_v{i}", description=f"MCU circuit. Layout {i}.")
        for i in (1, 2)
    ]
    family = block2image.BlockFamily(name="mcu", blocks=blocks)
    text = block2image.family_markdown(family, tmp_path)
    assert text.startswith("### mcu\n\nMCU circuit.\n")
    assert "#### mcu_v1\n\nLayout 1.\n" in text
    assert "#### mcu_v2\n\nLayout 2.\n" in text
    assert text.count("**Key matrix:**") == 1
    overview = block2image.overview_markdown([family], tmp_path)
    assert (
        "| [mcu](#mcu)<br>variants: [mcu_v1](#mcu_v1), [mcu_v2](#mcu_v2) |" in overview
    )
    assert "| MCU circuit. |" in overview


@requires_kicad_cli
def test_block2image(tmp_path):
    images = tmp_path / "images"
    readme = tmp_path / "README.md"
    result = block2image.main(
        ["--in", str(LIBRARY), "--out", str(images), "--readme", str(readme)]
    )
    assert result == 0
    # kicad-cli must not write project local files to design blocks
    assert not list(LIBRARY.glob("usb_*.kicad_block/*.kicad_prl"))

    # variants share schematic, it is rendered once
    assert sorted(p.name for p in images.iterdir()) == [
        "mcu_atmega32u4-schematic.svg",
        "mcu_atmega32u4_v1-pcb.svg",
        "mcu_atmega32u4_v2-pcb.svg",
        "usb_minimal-pcb.svg",
        "usb_minimal-schematic.svg",
        "usb_udb_clone-pcb.svg",
        "usb_udb_clone-schematic.svg",
    ]
    # cropped to content, A4 page is 297 x 210 mm
    _, _, width, height = _view_box(
        (images / "mcu_atmega32u4-schematic.svg").read_text()
    )
    assert width < 150 and height < 200
    for name in ("mcu_atmega32u4_v1", "mcu_atmega32u4_v2"):
        _, _, width, height = _view_box((images / f"{name}-pcb.svg").read_text())
        assert width < 60 and height < 40

    text = readme.read_text()
    # side of the block does not matter (kbplacer can flip it)
    assert "components on" not in text and "mirrored" not in text
    assert "![mcu_atmega32u4_v1 PCB](images/mcu_atmega32u4_v1-pcb.svg)" in text
    # circuit is described once, followed by variants
    assert text.count("### mcu_atmega32u4\n") == 1
    assert text.count("<summary>Components (15)</summary>") == 1
    assert text.count("| `GPIO0` | U1 pin 8 (PB0) |") == 1
    assert text.count("25 `GPIO` pins, up to 12×13 matrix (156 keys)") == 1
    assert text.index("### mcu_atmega32u4\n") < text.index("#### mcu_atmega32u4_v1")
    assert text.index("#### mcu_atmega32u4_v1") < text.index("#### mcu_atmega32u4_v2")
    assert "\nElongated layout with USB data lines leaving to the side.\n" in text
    # bundled library blocks are used by name
    assert "--preset mcu_atmega32u4_v2\n" in text
    assert "`MCU_D+`, `MCU_D-`" in text
    assert "| `GPIO24` | U1 pin 1 (PE6) |" in text
    assert "| C3-C6 | 0.1u | `Capacitor_SMD:C_0603_1608Metric` |" in text
    assert "![mcu_atmega32u4 schematic](images/mcu_atmega32u4-schematic.svg)" in text

    # blocks without variants, connected to the microcontroller with labels
    usb = text[text.index("### usb_minimal") :]
    assert usb.count("- **Key matrix:** none (no `GPIO<n>` labels)") == 2
    assert usb.count("- **Interface labels:** `MCU_D+`, `MCU_D-`") == 2
    assert "| J1 | USB_C_Receptacle_USB2.0_14P |" in usb
    assert "| R1-R2 | 5.1k | `Resistor_SMD:R_0603_1608Metric` |" in usb
