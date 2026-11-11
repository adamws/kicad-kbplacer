# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generate preview images and overview of KiCad design blocks (kbplacer presets).

For every design block (`<name>.kicad_block` directory) schematic and PCB
are exported to SVG with `kicad-cli` and cropped to their content.
Optionally, markdown overview of the blocks (description, `--preset` usage,
key matrix capacity, interface labels, components and the images) is written
to README file, between `<!-- presets:begin -->` and `<!-- presets:end -->`
markers, so the rest of the file can be edited by hand.

Blocks named `<name>_v<n>` with equal schematic are variants (different PCB
layouts of the same circuit), they are presented together: schematic, its
components and matrix pins once, then usage and PCB of each variant. Leading
sentences common to variant descriptions describe the whole family.

Requires `kicad-cli` (KiCad 10.0+, design blocks with PCB layout).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

DESIGN_BLOCK_SUFFIX = ".kicad_block"
DESIGN_BLOCK_LIBRARY_SUFFIX = ".kicad_blocks"
GPIO_LABEL_PATTERN = re.compile(r"^GPIO(\d+)$")
# variants of a block: `<name>_v<n>`, see `BlockFamily`
VARIANT_PATTERN = re.compile(r"^(.+)_v(\d+)$")
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

# library bundled with kbplacer, its blocks are used by name alone
BUNDLED_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "kbplacer"
    / "presets"
    / "kbplacer.kicad_blocks"
)

README_BEGIN = "<!-- presets:begin -->"
README_END = "<!-- presets:end -->"

PCB_LAYERS = "F.Cu,B.Cu,F.SilkS,B.SilkS,Edge.Cuts"
# KiCad's default editor background colors
SCHEMATIC_BACKGROUND = "#F5F4EF"
PCB_BACKGROUND = "#001023"
# margins around cropped content, in mm
SCHEMATIC_MARGIN = 2.54
PCB_MARGIN = 1.0
# size of exported images, in pixels per mm
SCHEMATIC_SCALE = 4.0
PCB_SCALE = 12.0

BBox = Tuple[float, float, float, float]


@dataclass
class Component:
    reference: str
    value: str
    footprint: str


@dataclass
class BlockInfo:
    name: str
    directory: Path
    description: str = ""
    keywords: str = ""
    components: List[Component] = field(default_factory=list)
    # GPIO<n> label -> (reference, pin number, pin function)
    gpio_pins: Dict[str, Tuple[str, str, str]] = field(default_factory=dict)
    interface_labels: List[str] = field(default_factory=list)
    power_nets: List[str] = field(default_factory=list)
    pcb_side: Optional[str] = None
    pcb_size: Optional[Tuple[float, float]] = None
    schematic_image: Optional[Path] = None
    pcb_image: Optional[Path] = None

    @property
    def schematic_path(self) -> Path:
        return self.directory / f"{self.name}.kicad_sch"

    @property
    def pcb_path(self) -> Path:
        return self.directory / f"{self.name}.kicad_pcb"

    @property
    def matrix_capacity(self) -> Tuple[int, int]:
        """Largest key matrix (rows, columns) which can be driven by GPIO pins."""
        count = len(self.gpio_pins)
        return count // 2, count - count // 2


def find_blocks(paths: Iterable[str]) -> List[Path]:
    """Design block directories of given block directories or block libraries."""
    blocks: List[Path] = []
    for path in map(Path, paths):
        if path.suffix == DESIGN_BLOCK_SUFFIX and path.is_dir():
            blocks.append(path)
        elif path.suffix == DESIGN_BLOCK_LIBRARY_SUFFIX and path.is_dir():
            blocks.extend(sorted(path.glob(f"*{DESIGN_BLOCK_SUFFIX}")))
        else:
            msg = f"'{path}' is neither design block nor design block library"
            raise ValueError(msg)
    return blocks


def _run_kicad_cli(*args: str) -> None:
    result = subprocess.run(
        ["kicad-cli", *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        msg = f"kicad-cli {' '.join(args)} failed:\n{output}"
        raise RuntimeError(msg)


def _numbers(text: str) -> List[float]:
    return [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?", text)]


def _path_points(d: str) -> List[Tuple[float, float]]:
    """End points of absolute SVG path commands."""
    points: List[Tuple[float, float]] = []
    for command, arguments in re.findall(r"([A-Za-z])([^A-Za-z]*)", d):
        values = _numbers(arguments)
        # arc: rx ry rotation large-arc sweep x y
        step, offset = (7, 5) if command.upper() == "A" else (2, 0)
        for i in range(0, len(values) - step + 1, step):
            points.append((values[i + offset], values[i + offset + 1]))
    return points


def svg_content_bbox(svg: str) -> Optional[BBox]:
    """Bounding box (x0, y0, x1, y1) of visible SVG content exported by KiCad.

    KiCad writes absolute coordinates only (`M`/`L`/`A`/`Z` paths, circles
    and rectangles). Texts are drawn as stroked paths, `<text>` elements are
    invisible (for search/selection), so they are ignored. Arcs contribute
    their end points only, they are small (rounded corners) in practice.
    """
    xs: List[float] = []
    ys: List[float] = []
    for d in re.findall(r'<path\b[^>]*?\sd="([^"]*)"', svg, re.S):
        for points in _path_points(d):
            xs.append(points[0])
            ys.append(points[1])
    for attrs in re.findall(r"<circle\b([^>]*)>", svg):
        a = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        cx, cy, r = float(a["cx"]), float(a["cy"]), float(a.get("r", 0))
        xs.extend((cx - r, cx + r))
        ys.extend((cy - r, cy + r))
    for attrs in re.findall(r"<rect\b([^>]*)>", svg):
        a = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        x, y = float(a["x"]), float(a["y"])
        xs.extend((x, x + float(a["width"])))
        ys.extend((y, y + float(a["height"])))
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def crop_svg(
    svg: str, *, margin: float, scale: float, background: str, title: str
) -> Tuple[str, Optional[BBox]]:
    """Crop KiCad SVG (mm units) to its content, set image size to `scale`
    pixels per mm and add opaque background. Returns new SVG and the content
    bounding box (without margin)."""
    bbox = svg_content_bbox(svg)
    if bbox is None:
        return svg, None
    x0, y0 = bbox[0] - margin, bbox[1] - margin
    width, height = bbox[2] - bbox[0] + 2 * margin, bbox[3] - bbox[1] + 2 * margin

    def _svg_tag(match: re.Match) -> str:
        tag = match.group(0)
        tag = re.sub(r'\swidth="[^"]*"', f' width="{math.ceil(width * scale)}"', tag)
        tag = re.sub(r'\sheight="[^"]*"', f' height="{math.ceil(height * scale)}"', tag)
        tag = re.sub(
            r'\sviewBox="[^"]*"',
            f' viewBox="{x0:.4f} {y0:.4f} {width:.4f} {height:.4f}"',
            tag,
        )
        rect = (
            f'\n<rect x="{x0:.4f}" y="{y0:.4f}" width="{width:.4f}" '
            f'height="{height:.4f}" fill="{background}" />'
        )
        return tag + rect

    svg = re.sub(r"<svg\b[^>]*>", _svg_tag, svg, count=1)
    # KiCad puts export date in the title, keep the output reproducible
    svg = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", svg, flags=re.S)
    return svg, bbox


def _isolated_copy(input_path: Path, directory: str) -> Path:
    """kicad-cli writes project local settings (`.kicad_prl`) next to its
    input, work on a copy to keep design blocks untouched."""
    source_dir = Path(directory) / "source"
    source_dir.mkdir()
    return Path(shutil.copy(input_path, source_dir))


def _export_svg(kind: str, input_path: Path, *args: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        source = str(_isolated_copy(input_path, tmpdir))
        if kind == "sch":
            _run_kicad_cli("sch", "export", "svg", "--output", tmpdir, *args, source)
            svgs = list(Path(tmpdir).glob("*.svg"))
            if len(svgs) != 1:
                msg = f"Expected single page schematic, got {len(svgs)} pages"
                raise RuntimeError(msg)
            return svgs[0].read_text()
        output = Path(tmpdir) / "pcb.svg"
        _run_kicad_cli("pcb", "export", "svg", "--output", str(output), *args, source)
        return output.read_text()


def render_schematic(block: BlockInfo, output_path: Path) -> None:
    # own background is added when cropping, KiCad one would cover whole page
    svg = _export_svg(
        "sch", block.schematic_path, "--exclude-drawing-sheet", "--no-background-color"
    )
    svg, _ = crop_svg(
        svg,
        margin=SCHEMATIC_MARGIN,
        scale=SCHEMATIC_SCALE,
        background=SCHEMATIC_BACKGROUND,
        title=f"{block.name} schematic",
    )
    output_path.write_text(svg)


def pcb_footprint_sides(pcb_text: str) -> Counter:
    """Number of footprints on `front` and `back` side of the board."""
    layers = re.findall(r'\(footprint\s+"[^"]*"\s*\(layer\s+"([FB])\.Cu"\)', pcb_text)
    return Counter("front" if layer == "F" else "back" for layer in layers)


def render_pcb(block: BlockInfo, output_path: Path, side: str) -> Tuple[float, float]:
    """Export block PCB as seen from `side` (back side is mirrored, so that
    its silkscreen is readable), returns PCB content size in mm.

    Block side does not matter for the user, kbplacer flips the block when
    other side is requested, so previews always show the components side."""
    args = [
        "--mode-single",
        "--exclude-drawing-sheet",
        "--page-size-mode",
        "2",
        "--layers",
        PCB_LAYERS,
    ]
    if side == "back":
        args.append("--mirror")
    svg = _export_svg("pcb", block.pcb_path, *args)
    svg, bbox = crop_svg(
        svg,
        margin=PCB_MARGIN,
        scale=PCB_SCALE,
        background=PCB_BACKGROUND,
        title=f"{block.name} PCB",
    )
    output_path.write_text(svg)
    if bbox is None:
        return 0.0, 0.0
    return round(bbox[2] - bbox[0], 1), round(bbox[3] - bbox[1], 1)


def _pin_function(node: ET.Element) -> str:
    function = node.get("pinfunction", "")
    pin = node.get("pin", "")
    # pins sharing a name are disambiguated with `_<number>` suffix
    if pin and function.endswith(f"_{pin}"):
        function = function[: -len(pin) - 1]
    return function


def read_block_info(directory: Path) -> BlockInfo:
    block = BlockInfo(name=directory.stem, directory=directory)
    metadata_path = directory / f"{block.name}.json"
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text())
        block.description = metadata.get("description", "")
        block.keywords = metadata.get("keywords", "")

    if block.schematic_path.is_file():
        text = block.schematic_path.read_text()
        global_labels = set(re.findall(r'\(global_label\s+"([^"]+)"', text))
        with tempfile.TemporaryDirectory() as tmpdir:
            netlist_path = Path(tmpdir) / "netlist.xml"
            _run_kicad_cli(
                "sch",
                "export",
                "netlist",
                "--format",
                "kicadxml",
                "--output",
                str(netlist_path),
                str(_isolated_copy(block.schematic_path, tmpdir)),
            )
            netlist = ET.parse(netlist_path).getroot()
        for comp in netlist.iter("comp"):
            block.components.append(
                Component(
                    reference=comp.get("ref", ""),
                    value=comp.findtext("value", ""),
                    footprint=comp.findtext("footprint", ""),
                )
            )
        for net in netlist.iter("net"):
            name = net.get("name", "")
            if GPIO_LABEL_PATTERN.match(name):
                node = net.find("node")
                if node is not None:
                    block.gpio_pins[name] = (
                        node.get("ref", ""),
                        node.get("pin", ""),
                        _pin_function(node),
                    )
            elif name in global_labels:
                block.interface_labels.append(name)
            elif not name.startswith(("/", "Net-(", "unconnected-(")):
                # remaining named nets come from power symbols
                block.power_nets.append(name)
        block.gpio_pins = dict(
            sorted(
                block.gpio_pins.items(),
                key=lambda item: int(GPIO_LABEL_PATTERN.match(item[0]).group(1)),
            )
        )

    if block.pcb_path.is_file():
        sides = pcb_footprint_sides(block.pcb_path.read_text())
        block.pcb_side = "back" if sides["back"] > sides["front"] else "front"
    return block


@dataclass
class BlockFamily:
    """Design blocks sharing schematic, differing only in PCB layout.

    Variants are recognized by `_v<n>` name suffix (`mcu_v1`, `mcu_v2`) and
    equal schematic. Block without variants is a family of its own."""

    name: str
    blocks: List[BlockInfo]

    @property
    def has_variants(self) -> bool:
        return len(self.blocks) > 1


def _schematic_signature(block: BlockInfo) -> Optional[str]:
    if not block.schematic_path.is_file():
        return None
    # UUIDs are regenerated whenever a block is saved, they do not matter
    return UUID_PATTERN.sub("", block.schematic_path.read_text())


def group_variants(blocks: List[BlockInfo]) -> List[BlockFamily]:
    families: Dict[Tuple[str, Optional[str]], List[BlockInfo]] = {}
    for block in blocks:
        match = VARIANT_PATTERN.match(block.name)
        base = match.group(1) if match else block.name
        signature = _schematic_signature(block) if match else block.name
        families.setdefault((base, signature), []).append(block)
    result = []
    for (base, _), members in families.items():
        if len(members) == 1:
            result.append(BlockFamily(name=members[0].name, blocks=members))
        else:
            members.sort(key=lambda b: _natural_key(b.name))
            result.append(BlockFamily(name=base, blocks=members))
    return result


def render_family(family: BlockFamily, output_dir: Path) -> None:
    first = family.blocks[0]
    if first.schematic_path.is_file():
        image = output_dir / f"{family.name}-schematic.svg"
        render_schematic(first, image)
        logger.info(f"Created {image}")
        for block in family.blocks:
            block.schematic_image = image
    for block in family.blocks:
        if block.pcb_side:
            block.pcb_image = output_dir / f"{block.name}-pcb.svg"
            block.pcb_size = render_pcb(block, block.pcb_image, block.pcb_side)
            logger.info(f"Created {block.pcb_image}")


def _relative(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path, start)).as_posix()


def _references_summary(references: List[str]) -> str:
    """`C1, C2, C3, C5` -> `C1-C3, C5`"""
    parts: List[str] = []
    previous: Optional[Tuple[str, int]] = None
    run_start = ""
    for reference in references + [""]:
        match = re.match(r"^(.*?)(\d+)$", reference)
        current = (match.group(1), int(match.group(2))) if match else None
        continues = (
            current
            and previous
            and current[0] == previous[0]
            and current[1] == previous[1] + 1
        )
        if not continues:
            if previous:
                last = f"{previous[0]}{previous[1]}"
                parts.append(last if last == run_start else f"{run_start}-{last}")
            run_start = reference
            if not current and reference:
                parts.append(reference)
        previous = current
    return ", ".join(parts)


def _natural_key(value: str) -> List:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", value)]


def _components_markdown(components: List[Component]) -> List[str]:
    if not components:
        return []
    groups: Dict[Tuple[str, str], List[str]] = {}
    for c in sorted(components, key=lambda c: _natural_key(c.reference)):
        groups.setdefault((c.value, c.footprint), []).append(c.reference)
    lines = [
        "<details>",
        f"<summary>Components ({len(components)})</summary>",
        "",
        "| References | Value | Footprint |",
        "| --- | --- | --- |",
    ]
    for (value, footprint), refs in sorted(
        groups.items(), key=lambda item: _natural_key(item[1][0])
    ):
        lines.append(f"| {_references_summary(refs)} | {value} | `{footprint}` |")
    return [*lines, "", "</details>", ""]


def _gpio_markdown(gpio_pins: Dict[str, Tuple[str, str, str]]) -> List[str]:
    if not gpio_pins:
        return []
    lines = [
        "<details>",
        "<summary>Matrix pins (<code>--matrix-pin-order</code> labels)</summary>",
        "",
        "| Label | Pin |",
        "| --- | --- |",
    ]
    for label, (reference, pin, function) in gpio_pins.items():
        description = f"{reference} pin {pin}"
        if function:
            description += f" ({function})"
        lines.append(f"| `{label}` | {description} |")
    return [*lines, "", "</details>", ""]


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def split_descriptions(descriptions: List[str]) -> Tuple[str, List[str]]:
    """Split variant descriptions to common leading sentences and the rest."""
    sentences = [_sentences(d) for d in descriptions]
    common: List[str] = []
    for candidates in zip(*sentences):
        if len(set(candidates)) != 1:
            break
        common.append(candidates[0])
    rest = [" ".join(s[len(common) :]) for s in sentences]
    return " ".join(common), rest


def _circuit_markdown(block: BlockInfo, name: str, readme_dir: Path) -> List[str]:
    """Facts, image and tables of block schematic (shared by variants)."""
    facts = []
    if block.gpio_pins:
        rows, columns = block.matrix_capacity
        facts.append(
            f"- **Key matrix:** {len(block.gpio_pins)} `GPIO` pins, "
            f"up to {rows}×{columns} matrix ({rows * columns} keys)"
        )
    else:
        facts.append("- **Key matrix:** none (no `GPIO<n>` labels)")
    if block.interface_labels:
        labels = ", ".join(f"`{n}`" for n in sorted(block.interface_labels))
        facts.append(f"- **Interface labels:** {labels}")
    if block.power_nets:
        nets = ", ".join(f"`{n}`" for n in sorted(block.power_nets))
        facts.append(f"- **Power:** {nets}")
    lines = [*facts, ""]
    if block.schematic_image:
        image = _relative(block.schematic_image, readme_dir)
        lines += [f"![{name} schematic]({image})", ""]
    lines += _components_markdown(block.components)
    lines += _gpio_markdown(block.gpio_pins)
    return lines


def _layout_markdown(block: BlockInfo, readme_dir: Path) -> List[str]:
    """Usage and PCB of the block (specific for a variant)."""
    lines = ["```shell", f"--preset {_block_identifier(block.directory)}", "```", ""]
    if block.pcb_size:
        width, height = block.pcb_size
        lines += [f"- **PCB:** {width} × {height} mm", ""]
    if block.pcb_image:
        image = _relative(block.pcb_image, readme_dir)
        lines += [f"![{block.name} PCB]({image})", ""]
    return lines


def _keywords(blocks: List[BlockInfo]) -> List[str]:
    keywords = list(dict.fromkeys(b.keywords for b in blocks if b.keywords))
    return [f"Keywords: {', '.join(keywords)}", ""] if keywords else []


def family_markdown(family: BlockFamily, readme_dir: Path) -> str:
    first = family.blocks[0]
    if not family.has_variants:
        lines = [f"### {first.name}", "", first.description or "_No description._"]
        lines += ["", *_keywords(family.blocks)]
        lines += _layout_markdown(first, readme_dir)
        lines += _circuit_markdown(first, first.name, readme_dir)
        return "\n".join(lines)

    common, specific = split_descriptions([b.description for b in family.blocks])
    variants = ", ".join(f"`{b.name}`" for b in family.blocks)
    lines = [f"### {family.name}", "", common or "_No description._", ""]
    lines += _keywords(family.blocks)
    lines += [
        f"Variants {variants} share the schematic and differ in PCB layout.",
        "",
    ]
    lines += _circuit_markdown(first, family.name, readme_dir)
    for block, description in zip(family.blocks, specific):
        lines += [f"#### {block.name}", ""]
        if description:
            lines += [description, ""]
        lines += _layout_markdown(block, readme_dir)
    return "\n".join(lines)


def _block_identifier(directory: Path) -> str:
    library = directory.parent
    if library.resolve() == BUNDLED_LIBRARY:
        return directory.stem
    if library.suffix == DESIGN_BLOCK_LIBRARY_SUFFIX:
        return f"{library.as_posix()}:{directory.stem}"
    return directory.as_posix()


def _anchor(heading: str) -> str:
    # GitHub heading anchors: lowercase, punctuation other than `-`/`_` removed
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def overview_markdown(families: List[BlockFamily], readme_dir: Path) -> str:
    """Table of all blocks with PCB thumbnails, linking to block sections."""
    lines = [
        "| Preset | Description | Key matrix | PCB |",
        "| --- | --- | --- | --- |",
    ]
    for family in families:
        first = family.blocks[0]
        preset = f"[{family.name}](#{_anchor(family.name)})"
        description, _ = split_descriptions([b.description for b in family.blocks])
        if family.has_variants:
            variants = ", ".join(
                f"[{b.name}](#{_anchor(b.name)})" for b in family.blocks
            )
            preset += f"<br>variants: {variants}"
        matrix = "-"
        if first.gpio_pins:
            rows, columns = first.matrix_capacity
            matrix = f"{len(first.gpio_pins)} pins, up to {rows}×{columns}"
        images = [
            f'<a href="#{_anchor(b.name)}">'
            f'<img src="{_relative(b.pcb_image, readme_dir)}"'
            f' alt="{b.name} PCB" height="80"></a>'
            for b in family.blocks
            if b.pcb_image
        ]
        pcb = " ".join(images) or "-"
        lines.append(f"| {preset} | {description} | {matrix} | {pcb} |")
    return "\n".join(lines) + "\n"


def update_readme(readme_path: Path, families: List[BlockFamily]) -> None:
    readme_dir = readme_path.parent
    sections = [family_markdown(f, readme_dir) for f in families]
    generated = (
        f"{README_BEGIN}\n"
        "<!-- generated with tools/block2image.py, do not edit by hand -->\n\n"
        + overview_markdown(families, readme_dir)
        + "\n"
        + "\n".join(sections).rstrip()
        + f"\n\n{README_END}"
    )
    text = readme_path.read_text() if readme_path.is_file() else ""
    if README_BEGIN in text and README_END in text:
        begin = text.index(README_BEGIN)
        end = text.index(README_END) + len(README_END)
        text = text[:begin] + generated + text[end:]
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + generated + "\n"
    readme_path.write_text(text)
    logger.info(f"Updated {readme_path}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Design blocks to preview images and markdown overview"
    )
    parser.add_argument(
        "-i",
        "--in",
        nargs="+",
        required=True,
        help="Design block (*.kicad_block) or design block library (*.kicad_blocks)",
    )
    parser.add_argument(
        "-o", "--out", required=True, help="Output directory for images"
    )
    parser.add_argument(
        "--readme",
        help=(
            "Markdown file to write blocks overview to, content between "
            f"'{README_BEGIN}' and '{README_END}' markers is replaced "
            "(appended when no markers). Blocks of the library bundled with "
            "kbplacer are identified by name, other by `--in` path"
        ),
    )
    parser.add_argument(
        "--log-level",
        required=False,
        default="WARNING",
        choices=logging._nameToLevel.keys(),
        type=str,
        help="Provide logging level, default=%(default)s",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level, format="%(asctime)s: %(message)s", datefmt="%H:%M:%S"
    )

    if not shutil.which("kicad-cli"):
        logger.error("kicad-cli not found")
        return 1
    try:
        directories = find_blocks(getattr(args, "in"))
    except ValueError as e:
        logger.error(e)
        return 1

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    families = group_variants([read_block_info(d) for d in directories])
    for family in families:
        render_family(family, output_dir)
    if args.readme:
        update_readme(Path(args.readme), families)
    return 0


if __name__ == "__main__":
    sys.exit(main())
