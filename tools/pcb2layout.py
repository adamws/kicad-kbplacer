# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reverse-engineer keyboard layout (KLE json) from KiCad PCB file.

Reverses what `kbplacer` does: key switch footprints are located, their
positions and orientations are converted back to KLE coordinates
(key units, rotation clusters) and key sizes are recovered either from
footprint names (e.g. `SW_Cherry_MX_PCB_1.50u`), stabilizer footprints
or by fitting key widths between neighbouring keys.

Optionally keys can be annotated with via-style `row,column` labels
derived from the key matrix netlist.

Result can be verified by creating new PCB out of recovered layout with
kbplacer and comparing switch footprint positions of both boards.
"""

from __future__ import annotations

import argparse
import copy
import logging
import math
import os
import re
import string
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pcbnew

from kbplacer.board_builder import BoardBuilder
from kbplacer.defaults import DEFAULT_DIODE_POSITION
from kbplacer.element_position import (
    ElementInfo,
    ElementPosition,
    PositionOption,
    Side,
)
from kbplacer.key_placer import KeyPlacer
from kbplacer.kle_serial import Key, Keyboard, MatrixAnnotatedKeyboard

logger = logging.getLogger(__name__)

# Key widths (in units) which are considered when guessing key size
UNSTABILIZED_WIDTHS = [1, 1.25, 1.5, 1.75]
STABILIZED_WIDTHS = [2, 2.25, 2.5, 2.75, 3, 6, 6.25, 7]
STANDARD_WIDTHS = UNSTABILIZED_WIDTHS + STABILIZED_WIDTHS

# Common 1U key distances (in mm) used for snapping guessed spacing
STANDARD_SPACINGS = [19.05, 19.0, 18.5, 18.0, 17.5, 17.0, 16.0]

# Label indexes used by kbplacer
MATRIX_COORDINATES_LABEL = MatrixAnnotatedKeyboard.MATRIX_COORDINATES_LABEL
LAYOUT_OPTION_LABEL = MatrixAnnotatedKeyboard.LAYOUT_OPTION_LABEL
EXPLICIT_ANNOTATION_LABEL = 10

SWITCH_NAME_RE = re.compile(
    r"(?i)(cherry|(?<![a-z])mx(?![a-z])|choc|kailh|gateron|alps|matias|outemu|"
    r"hot[-_ ]?swap|key[-_ ]?switch|pg13\d\d|pg1232|romer|(?<![a-z])ks-?\d\d)"
)
ENCODER_NAME_RE = re.compile(r"(?i)(rotary|encoder|ec11|ec12)")
# footprints which accept either key switch or encoder (decided on assembly),
# e.g. `keyswitch_cherrymx_hotswap_1u_rotary_encoder_ec12`. Alps is excluded,
# it is common encoder manufacturer (`RotaryEncoder_Alps_EC11E-Switch...`)
HYBRID_SWITCH_NAME_RE = re.compile(
    r"(?i)(cherry|(?<![a-z])mx(?![a-z])|choc|kailh|gateron|hot[-_ ]?swap|"
    r"key[-_ ]?switch)"
)
EXCLUDED_NAME_RE = re.compile(
    r"(?i)(stab|diode|capacitor|resistor|mounting|spst|spdt|tactile|"
    r"^sw_push|pts\d|skqg|tl33|evq)"
)
STABILIZER_NAME_RE = re.compile(r"(?i)stab")
DIODE_NAME_RE = re.compile(r"(?i)(diode|^d_|sod-?\d|sot-?23|do-?3[45]|minimelf|1n4148)")
WIDTH_IN_NAME_RE = re.compile(r"(?i)(?<![\d.])(\d+(?:[.,]\d+)?)\s*u(?![a-z])")
ISO_ENTER_NAME_RE = re.compile(r"(?i)iso")
VERTICAL_NAME_RE = re.compile(r"(?i)vertical")
DEFAULT_ROW_NET_RE = re.compile(r"(?i)^(?:.*/)?(?:row|r)[_-]?(\d+)$")
DEFAULT_COLUMN_NET_RE = re.compile(r"(?i)^(?:.*/)?(?:column|col|c)[_-]?(\d+)$")
FALLBACK_SWITCH_PREFIXES = ["SW", "K", "KEY", "S", "MX"]

# exit status when verification score is below --verify-min-score
# (2 is used by argparse for usage errors)
EXIT_LOW_SCORE = 3

EPS = 0.01  # in key units
PRECISION = 4  # decimal places of key coordinates in output


@dataclass
class Options:
    switch_pattern: str = ""
    switch_footprint_regex: str = ""
    diode_pattern: str = ""
    stabilizer_pattern: str = ""
    key_distance: Optional[Tuple[float, float]] = None
    switch_orientation: Optional[float] = None
    encoder_adjustment: Optional[Tuple[float, float]] = None
    hybrid_encoders: str = "alternative"
    width_source: str = "auto"
    matrix_labels: bool = False
    row_pattern: str = ""
    column_pattern: str = ""
    diode_side: str = "row"
    alternatives_in_place: bool = False
    explicit_annotation: bool = False
    grid: float = 0.125
    grid_tolerance: float = 0.0005


@dataclass
class Stabilizer:
    reference: str
    footprint_name: str
    position: Tuple[float, float]
    orientation: float
    name_width: Optional[float]


@dataclass
class Switch:
    footprint: pcbnew.FOOTPRINT
    reference: str
    annotation: str
    footprint_name: str
    position: Tuple[float, float]  # mm, footprint anchor
    orientation: float  # KiCad degrees
    back: bool
    encoder: bool
    # footprint for either key switch or encoder, `encoder` tells which
    # one is assumed for the main layout
    hybrid: bool
    name_width: Optional[float]
    iso: bool
    vertical_name: bool
    stabilizer: Optional[Stabilizer] = None


@dataclass
class PlacedKey:
    switch: Switch
    angle: float  # KLE convention, clockwise positive
    switch_rotation: float
    cluster: int
    local: Tuple[float, float]  # key center in cluster frame (mm)
    width: float = 1
    height: float = 1
    iso: bool = False
    allowed_widths: List[float] = field(default_factory=lambda: [1])
    # True when allowed widths come from footprint name or stabilizer
    width_evidence: bool = False
    matrix: Optional[Tuple[str, str]] = None
    option: Optional[Tuple[int, int]] = None  # layout option (group, choice)
    encoder: bool = False
    # positions in key units, filled during conversion:
    center_u: Tuple[float, float] = (0, 0)

    @property
    def vertical(self) -> bool:
        return self.height > self.width


@dataclass
class Cluster:
    angle: float
    origin: Tuple[float, float]  # mm


def natural_key(text: str) -> List:
    return [int(c) if c.isdigit() else c for c in re.split(r"(\d+)", text)]


def normalize_angle(angle: float) -> float:
    angle = math.fmod(angle, 360)
    if angle > 180:
        angle -= 360
    elif angle <= -180:
        angle += 360
    return round(angle, 6) + 0.0  # avoid -0.0


def rotate_point(
    point: Tuple[float, float], origin: Tuple[float, float], angle: float
) -> Tuple[float, float]:
    """Rotate point around origin by angle in KLE convention
    (screen coordinates, y axis pointing down, clockwise positive)"""
    rad = math.radians(angle)
    x, y = point[0] - origin[0], point[1] - origin[1]
    x1 = x * math.cos(rad) - y * math.sin(rad)
    y1 = x * math.sin(rad) + y * math.cos(rad)
    return x1 + origin[0], y1 + origin[1]


def _split_pattern(pattern: str) -> Tuple[str, str]:
    if "{}" not in pattern:
        msg = f"Pattern '{pattern}' must contain '{{}}' placeholder"
        raise ValueError(msg)
    before, after = pattern.split("{}", 1)
    return before, after


def pattern_to_regex(pattern: str, value: str = "(.+)") -> re.Pattern:
    """Convert kbplacer-like annotation pattern (e.g. `SW{}`) to regex"""
    before, after = _split_pattern(pattern)
    return re.compile(f"^{re.escape(before)}{value}{re.escape(after)}$")


def net_pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert net name pattern (e.g. `ROW{}`) to regex, allow hierarchical
    sheet path prefix"""
    before, after = _split_pattern(pattern)
    return re.compile(f"^(?:.*/)?{re.escape(before)}(\\d+){re.escape(after)}$")


def width_from_name(name: str) -> Optional[float]:
    if match := WIDTH_IN_NAME_RE.search(name):
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            return None
    return None


def _position_mm(item: pcbnew.BOARD_ITEM) -> Tuple[float, float]:
    position = item.GetPosition()
    return pcbnew.ToMM(position.x), pcbnew.ToMM(position.y)


def _footprint_name(footprint: pcbnew.FOOTPRINT) -> str:
    return str(footprint.GetFPID().GetLibItemName())


def _reference_prefix(reference: str) -> str:
    match = re.match(r"^([A-Za-z_]+)", reference)
    return match.group(1) if match else ""


def _annotation(reference: str, pattern: Optional[re.Pattern]) -> str:
    if pattern and (match := pattern.match(reference)):
        return match.group(1)
    return reference.lstrip(string.ascii_letters + "_")


def find_switch_footprints(
    board: pcbnew.BOARD, opts: Options
) -> Tuple[List[pcbnew.FOOTPRINT], Optional[re.Pattern]]:
    """Find key switch footprints, either by user provided reference pattern
    and/or footprint name regex or by educated guess based on footprint names"""
    footprints = list(board.GetFootprints())
    pattern = pattern_to_regex(opts.switch_pattern) if opts.switch_pattern else None
    name_regex = (
        re.compile(opts.switch_footprint_regex, re.IGNORECASE)
        if opts.switch_footprint_regex
        else None
    )

    if pattern or name_regex:
        result = []
        for f in footprints:
            if pattern and not pattern.match(f.GetReference()):
                continue
            if name_regex and not name_regex.search(_footprint_name(f)):
                continue
            result.append(f)
        return result, pattern

    def _is_switch_name(name: str) -> bool:
        if ENCODER_NAME_RE.search(name):
            return True
        return bool(SWITCH_NAME_RE.search(name)) and not EXCLUDED_NAME_RE.search(name)

    by_name = [f for f in footprints if _is_switch_name(_footprint_name(f))]
    if by_name:
        logger.info(f"Found {len(by_name)} switch footprints by footprint name")
        return by_name, None

    # nothing recognized by name, fallback to most common reference prefix
    prefixes = Counter(_reference_prefix(f.GetReference()) for f in footprints)
    for prefix in FALLBACK_SWITCH_PREFIXES:
        if prefixes.get(prefix):
            pattern = pattern_to_regex(prefix + "{}")
            result = [
                f
                for f in footprints
                if pattern.match(f.GetReference())
                and not EXCLUDED_NAME_RE.search(_footprint_name(f))
            ]
            logger.info(
                f"Found {len(result)} switch footprints by '{prefix}' reference prefix"
            )
            return result, pattern
    return [], None


def _is_stabilizer(footprint: pcbnew.FOOTPRINT, pattern: Optional[re.Pattern]) -> bool:
    if pattern:
        return bool(pattern.match(footprint.GetReference()))
    return bool(STABILIZER_NAME_RE.search(_footprint_name(footprint)))


def find_stabilizers(
    board: pcbnew.BOARD,
    switches: List[Switch],
    switch_pattern: Optional[re.Pattern],
    opts: Options,
    key_distance: float,
) -> None:
    """Associate stabilizer footprints with switches, by annotation when
    possible (`ST1` with `SW1`) or by distance otherwise"""
    pattern = (
        pattern_to_regex(opts.stabilizer_pattern) if opts.stabilizer_pattern else None
    )
    switch_refs = {s.reference for s in switches}
    stabilizers = [
        f
        for f in board.GetFootprints()
        if f.GetReference() not in switch_refs and _is_stabilizer(f, pattern)
    ]
    by_annotation = {s.annotation: s for s in switches}
    for f in stabilizers:
        stab = Stabilizer(
            reference=f.GetReference(),
            footprint_name=_footprint_name(f),
            position=_position_mm(f),
            orientation=f.GetOrientationDegrees(),
            name_width=width_from_name(_footprint_name(f)),
        )
        annotation = _annotation(stab.reference, pattern)
        switch = by_annotation.get(annotation)
        if (
            switch is None
            or switch.stabilizer is not None
            # annotations of switches and stabilizers may be unrelated
            or math.dist(switch.position, stab.position) > key_distance
        ):
            switch = None
            # stabilizer footprints are usually centered at switch position
            best_distance = 0.5 * key_distance
            for s in switches:
                if s.stabilizer is not None or s.encoder:
                    continue
                distance = math.dist(s.position, stab.position)
                if distance < best_distance:
                    best_distance = distance
                    switch = s
        if switch is not None:
            logger.debug(f"Stabilizer {stab.reference} belongs to {switch.reference}")
            switch.stabilizer = stab
        else:
            logger.warning(f"Could not associate {stab.reference} with any switch")


def is_hybrid_name(name: str) -> bool:
    return bool(ENCODER_NAME_RE.search(name) and HYBRID_SWITCH_NAME_RE.search(name))


def collect_switches(
    footprints: List[pcbnew.FOOTPRINT],
    pattern: Optional[re.Pattern],
    hybrid_encoders: str = "alternative",
) -> List[Switch]:
    switches = []
    for f in footprints:
        name = _footprint_name(f)
        hybrid = is_hybrid_name(name)
        encoder = bool(ENCODER_NAME_RE.search(name))
        if hybrid and hybrid_encoders != "encoder":
            encoder = False
        switches.append(
            Switch(
                footprint=f,
                reference=f.GetReference(),
                annotation=_annotation(f.GetReference(), pattern),
                footprint_name=name,
                position=_position_mm(f),
                orientation=f.GetOrientationDegrees(),
                back=f.GetLayer() == pcbnew.B_Cu,
                encoder=encoder,
                hybrid=hybrid,
                name_width=width_from_name(name),
                iso=bool(ISO_ENTER_NAME_RE.search(name)),
                vertical_name=bool(VERTICAL_NAME_RE.search(name)),
            )
        )
    switches.sort(key=lambda s: natural_key(s.reference))
    return switches


def guess_reference_orientation(switches: List[Switch], back: bool) -> float:
    """Most common orientation which is multiple of 90 degrees is assumed to
    be the orientation of non-rotated keys"""
    orientations = Counter(
        round(normalize_angle(s.orientation), 2) for s in switches if s.back == back
    )
    for orientation, _ in orientations.most_common():
        if orientation % 90 == 0:
            return orientation
    return 0


def _matrix_pads_nets(switch: Switch) -> Set[str]:
    def _valid(net: str) -> bool:
        return bool(net) and not net.startswith("unconnected-")

    pads = list(switch.footprint.Pads())
    if switch.encoder or switch.hybrid:
        encoder_pads = [p for p in pads if p.GetNumber() in ("S1", "S2")]
        if encoder_pads:
            pads = encoder_pads
    nets = {p.GetNetname() for p in pads if _valid(p.GetNetname())}
    if len(nets) > 2:
        nets = {
            p.GetNetname()
            for p in pads
            if p.GetNumber() in ("1", "2") and _valid(p.GetNetname())
        }
    return nets


def resolve_matrix_positions(
    board: pcbnew.BOARD, switches: List[Switch], opts: Options
) -> Dict[str, Tuple[str, str]]:
    """Find (row, column) matrix position of each switch based on netlist"""
    diode_pattern = pattern_to_regex(opts.diode_pattern) if opts.diode_pattern else None
    switch_refs = {s.reference for s in switches}

    def _is_diode(f: pcbnew.FOOTPRINT) -> bool:
        reference = f.GetReference()
        if reference in switch_refs:
            return False
        if diode_pattern:
            return bool(diode_pattern.match(reference))
        name = _footprint_name(f)
        if "led" in name.lower():
            return False
        return bool(re.match(r"^D\d", reference)) or bool(DIODE_NAME_RE.search(name))

    footprints_by_net: Dict[str, Set[str]] = defaultdict(set)
    diode_nets: Dict[str, Set[str]] = {}
    for f in board.GetFootprints():
        nets = {p.GetNetname() for p in f.Pads() if p.GetNetname()}
        for net in nets:
            footprints_by_net[net].add(f.GetReference())
        if _is_diode(f):
            diode_nets[f.GetReference()] = nets

    row_re = net_pattern_to_regex(opts.row_pattern) if opts.row_pattern else None
    column_re = (
        net_pattern_to_regex(opts.column_pattern) if opts.column_pattern else None
    )

    def _is_row(net: str) -> bool:
        return bool((row_re or DEFAULT_ROW_NET_RE).match(net))

    def _is_column(net: str) -> bool:
        return bool((column_re or DEFAULT_COLUMN_NET_RE).match(net))

    rows: Dict[str, str] = {}
    columns: Dict[str, str] = {}
    for switch in switches:
        resolved: List[Tuple[str, bool]] = []
        for net in sorted(_matrix_pads_nets(switch)):
            connected = footprints_by_net[net]
            diodes = [r for r in connected if r in diode_nets]
            others = [r for r in connected if r not in diode_nets]
            # switch-diode net, there might be more than one diode in parallel
            if diodes and all(r in switch_refs for r in others):
                other_nets = set().union(*(diode_nets[d] for d in diodes)) - {net}
                if len(other_nets) == 1:
                    resolved.append((next(iter(other_nets)), True))
                    continue
            resolved.append((net, False))

        matrix_nets = list(dict.fromkeys(n for n, _ in resolved))
        if len(matrix_nets) != 2:
            logger.warning(
                f"Switch {switch.reference} does not have exactly two matrix nets "
                f"(got: {matrix_nets}), skipping matrix annotation"
            )
            continue

        row_net = column_net = None
        if _is_row(matrix_nets[0]) and _is_column(matrix_nets[1]):
            row_net, column_net = matrix_nets
        elif _is_row(matrix_nets[1]) and _is_column(matrix_nets[0]):
            column_net, row_net = matrix_nets
        else:
            via_diode = [n for n, d in resolved if d]
            plain = [n for n, d in resolved if not d]
            if len(via_diode) == 1 and len(plain) == 1:
                if opts.diode_side == "row":
                    row_net, column_net = via_diode[0], plain[0]
                else:
                    column_net, row_net = via_diode[0], plain[0]
        if row_net is None or column_net is None:
            logger.warning(
                f"Could not determine row and column of {switch.reference} "
                f"(nets: {matrix_nets}), skipping matrix annotation"
            )
            continue
        rows[switch.reference] = row_net
        columns[switch.reference] = column_net

    def _indexes(nets: Iterable[str], regex: Optional[re.Pattern]) -> Dict[str, str]:
        unique = sorted(set(nets), key=natural_key)
        result = {}
        for net in unique:
            match = (regex.match(net) if regex else None) or re.search(r"(\d+)$", net)
            if not match:
                break
            result[net] = str(int(match.group(1)))
        else:
            if len(set(result.values())) == len(result):
                return result
        # fallback to order of natural sort
        logger.info(f"Assigning matrix indexes by net names order: {unique}")
        return {net: str(i) for i, net in enumerate(unique)}

    row_indexes = _indexes(rows.values(), row_re)
    column_indexes = _indexes(columns.values(), column_re)
    return {
        reference: (row_indexes[rows[reference]], column_indexes[columns[reference]])
        for reference in rows
    }


def build_placed_keys(
    switches: List[Switch], opts: Options
) -> Tuple[List[PlacedKey], List[Cluster]]:
    """Convert switch footprint positions to key centers in rotation cluster
    frames (still in mm)"""
    reference_orientation = {}
    for back in (False, True):
        if opts.switch_orientation is not None:
            reference_orientation[back] = opts.switch_orientation
        else:
            reference_orientation[back] = guess_reference_orientation(switches, back)
    logger.info(f"Reference switch orientation: {reference_orientation}")

    clusters: List[Cluster] = []
    keys: List[PlacedKey] = []
    pending: List[Tuple[Switch, float, float, Tuple[float, float]]] = []
    for switch in switches:
        relative = normalize_angle(
            reference_orientation[switch.back] - switch.orientation
        )
        angle, switch_rotation = relative, 0.0
        square = switch.name_width in (None, 1.0) and not switch.iso
        if relative != 0 and relative % 90 == 0 and (square or relative == 180):
            # can't distinguish key rotation from switch rotation,
            # prefer switch rotation since it does not affect key shape
            angle, switch_rotation = 0.0, relative % 360

        center = switch.position
        # hybrid footprints are positioned as switches, no adjustment
        if switch.encoder and not switch.hybrid and opts.encoder_adjustment:
            adjustment = rotate_point(opts.encoder_adjustment, (0, 0), angle)
            center = (center[0] - adjustment[0], center[1] - adjustment[1])
        pending.append((switch, angle, switch_rotation, center))

    # first key (top-left most) of each angle defines rotation origin
    for switch, angle, switch_rotation, center in sorted(
        pending, key=lambda p: (p[3][1], p[3][0])
    ):
        for i, cluster in enumerate(clusters):
            if math.isclose(cluster.angle, angle, abs_tol=1e-3):
                index = i
                break
        else:
            clusters.append(Cluster(angle=angle, origin=center))
            index = len(clusters) - 1
        cluster = clusters[index]
        local = rotate_point(center, cluster.origin, -cluster.angle)
        keys.append(
            PlacedKey(
                switch=switch,
                angle=cluster.angle,
                switch_rotation=switch_rotation,
                cluster=index,
                local=local,
                encoder=switch.encoder,
            )
        )
    keys.sort(key=lambda k: natural_key(k.switch.reference))
    return keys, clusters


def _guess_spacing(values: List[float]) -> Optional[float]:
    """Most common of the standard spacings found in values, or most common
    value if none of the standard spacings found. Standard spacings are
    preferred because overlapping alternative layout keys or wide keys may
    produce misleading neighbour distances"""
    if not values:
        return None
    tolerance = 0.02
    standard: Counter = Counter()
    for v in values:
        nearest = min(STANDARD_SPACINGS, key=lambda s: abs(v - s))
        if abs(v - nearest) <= tolerance:
            standard[nearest] += 1
    if standard:
        return max(standard.items(), key=lambda item: (item[1], item[0]))[0]
    rounded = Counter(round(v, 2) for v in values)
    best = max(rounded.items(), key=lambda item: (item[1], item[0]))[0]
    close = [v for v in values if abs(v - best) <= tolerance]
    return round(sum(close) / len(close), 3)


def guess_key_distance(keys: List[PlacedKey]) -> Tuple[float, float]:
    """Guess 1U distance by looking at most common distance between
    horizontal and vertical neighbours"""
    horizontal: List[float] = []
    for key in keys:
        best: Optional[Tuple[float, PlacedKey]] = None
        for other in keys:
            if other is key or other.cluster != key.cluster:
                continue
            dx = other.local[0] - key.local[0]
            dy = other.local[1] - key.local[1]
            # mostly horizontal neighbour, allow column stagger
            if dx > 1.0 and abs(dy) < 0.5 * dx and (best is None or dx < best[0]):
                best = (dx, other)
        if best:
            w1 = key.switch.name_width or 1
            w2 = best[1].switch.name_width or 1
            horizontal.append(best[0] / ((w1 + w2) / 2))
    spacing_x = _guess_spacing(horizontal)

    vertical: List[float] = []
    for key in keys:
        nearest: Optional[float] = None
        for other in keys:
            if other is key or other.cluster != key.cluster:
                continue
            dx = other.local[0] - key.local[0]
            dy = other.local[1] - key.local[1]
            if dy > 1.0 and abs(dx) < 0.5 * dy and (nearest is None or dy < nearest):
                nearest = dy
        if nearest:
            vertical.append(nearest)
    spacing_y = _guess_spacing(vertical)

    if spacing_x is None and spacing_y is None:
        return 19.05, 19.05
    if spacing_x is None:
        spacing_x = spacing_y
    if spacing_y is None:
        spacing_y = spacing_x
    return spacing_x, spacing_y  # type: ignore


def _stabilized_widths(stab: Stabilizer) -> List[float]:
    if stab.name_width and stab.name_width >= 2:
        # stabilizer of nearest smaller size is used when exact not available
        n = stab.name_width
        return [w for w in STABILIZED_WIDTHS if n - EPS <= w < n + 1 + EPS]
    return list(STABILIZED_WIDTHS)


def assign_initial_sizes(
    keys: List[PlacedKey], width_source: str, board_has_stabilizers: bool
) -> None:
    # when all switches use the same footprint, its name carries no
    # information about key size (most likely size agnostic footprint
    # like hotswap socket or footprint named '1u' used for all keys)
    uniform = len({k.switch.footprint_name for k in keys if not k.switch.encoder}) == 1
    for key in keys:
        switch = key.switch
        stab = switch.stabilizer
        key.width_evidence = False
        if switch.encoder or width_source == "none":
            key.width = key.height = 1
            key.allowed_widths = [1]
            continue
        if switch.iso and width_source != "neighbors":
            key.iso = True
            key.width, key.height = 1.25, 2
            key.allowed_widths = [1.25]
            continue

        stab_vertical = False
        if stab:
            relative = normalize_angle(stab.orientation - switch.orientation)
            stab_vertical = abs(abs(relative) - 90) < 1
            if key.switch_rotation in (90, 270):
                stab_vertical = not stab_vertical

        name_width = switch.name_width
        # 1U footprint with stabilizer means that footprint size is not reliable
        if name_width is not None and stab and name_width < 2:
            name_width = None
        if width_source == "neighbors" or (width_source == "auto" and uniform):
            name_width = None

        vertical = switch.vertical_name or stab_vertical
        if vertical:
            size = name_width or (stab.name_width if stab else None) or 2
            key.width, key.height = 1, size
            key.allowed_widths = [1]
        elif name_width is not None:
            key.width = name_width
            key.allowed_widths = [name_width]
            key.width_evidence = True
        elif width_source == "name":
            key.width = stab.name_width if stab and stab.name_width else 1
            key.allowed_widths = [key.width]
        elif stab:
            key.allowed_widths = _stabilized_widths(stab)
            key.width = key.allowed_widths[0]
            key.width_evidence = True
        elif board_has_stabilizers:
            key.allowed_widths = list(UNSTABILIZED_WIDTHS)
            key.width = 1
        else:
            key.allowed_widths = list(STANDARD_WIDTHS)
            key.width = 1


def _width_penalty(key: PlacedKey, width: float) -> float:
    # small penalty prefers keys of equal size when ambiguous,
    # (e.g. two 1.25U keys over 1U and 1.5U)
    penalty = 0.01 * (width - 1) ** 2
    if width >= 2 and not key.width_evidence:
        # keys which would require stabilizer but there is none, are accepted
        # only when such width closes gaps on both sides
        penalty += 1.01
    return penalty


def solve_row_widths(
    row: List[PlacedKey], left_bound: float, right_bound: Optional[float] = None
) -> Optional[List[float]]:
    """Choose widths of keys in a row (sorted by x) minimizing the number
    of gaps between neighbouring keys (dynamic programming over widths)"""

    def _gap_cost(gap: float) -> int:
        return 1 if gap > EPS else 0

    first = row[0]
    layer: Dict[float, Tuple[float, Optional[float]]] = {}
    for w in first.allowed_widths:
        edge = first.center_u[0] - w / 2
        if edge < left_bound - EPS and len(first.allowed_widths) > 1:
            continue
        layer[w] = (_gap_cost(edge - left_bound) + _width_penalty(first, w), None)
    history = [layer]

    for previous, key in zip(row, row[1:]):
        dx = key.center_u[0] - previous.center_u[0]
        current: Dict[float, Tuple[float, Optional[float]]] = {}
        for w in key.allowed_widths:
            best: Optional[Tuple[float, Optional[float]]] = None
            for pw, (cost, _) in history[-1].items():
                gap = dx - (pw + w) / 2
                if gap < -EPS:
                    continue
                c = cost + _gap_cost(gap) + _width_penalty(key, w)
                if best is None or c < best[0]:
                    best = (c, pw)
            if best is not None:
                current[w] = best
        if not current:
            return None
        history.append(current)

    if right_bound is not None:
        last = row[-1]
        final: Dict[float, Tuple[float, Optional[float]]] = {}
        for w, (cost, previous_width) in history[-1].items():
            gap = right_bound - (last.center_u[0] + w / 2)
            if gap >= -EPS:
                final[w] = (cost + _gap_cost(gap), previous_width)
        if not final:
            return None
        history[-1] = final

    width = min(history[-1].items(), key=lambda item: item[1][0])[0]
    result = [width]
    for layer in reversed(history[1:]):
        width = layer[width][1]  # type: ignore
        result.append(width)
    return list(reversed(result))


def _key_rects(key: PlacedKey) -> List[Tuple[float, float, float, float]]:
    """Key shape as list of (x, y, w, h) rectangles relative to key center
    in key units (before rotation)"""
    w, h = key.width, key.height
    rects = [(-w / 2, -h / 2, w, h)]
    if key.iso:
        rects.append((-w / 2 - 0.25, -h / 2, 1.5, 1))
    return rects


def _polygons(
    key: PlacedKey, spacing: Tuple[float, float], shrink: float
) -> List[List[Tuple[float, float]]]:
    sx, sy = spacing
    result = []
    for x, y, w, h in _key_rects(key):
        corners = [
            (x + shrink, y + shrink),
            (x + w - shrink, y + shrink),
            (x + w - shrink, y + h - shrink),
            (x + shrink, y + h - shrink),
        ]
        polygon = []
        for cx, cy in corners:
            px = key.local[0] + cx * sx
            py = key.local[1] + cy * sy
            polygon.append((px, py))
        result.append(polygon)
    return result


def _separated(a: List[Tuple[float, float]], b: List[Tuple[float, float]]) -> bool:
    for polygon in (a, b):
        for i in range(len(polygon)):
            p1, p2 = polygon[i], polygon[(i + 1) % len(polygon)]
            normal = (p2[1] - p1[1], p1[0] - p2[0])
            proj_a = [normal[0] * p[0] + normal[1] * p[1] for p in a]
            proj_b = [normal[0] * p[0] + normal[1] * p[1] for p in b]
            if max(proj_a) < min(proj_b) or max(proj_b) < min(proj_a):
                return True
    return False


def keys_overlap(
    k1: PlacedKey,
    k2: PlacedKey,
    clusters: List[Cluster],
    spacing: Tuple[float, float],
    shrink: float = 0.05,
) -> bool:
    """Check if keys overlap, ignoring overlaps smaller than `shrink`
    (in key units) on each side"""

    def _global(key: PlacedKey) -> List[List[Tuple[float, float]]]:
        cluster = clusters[key.cluster]
        return [
            [rotate_point(p, cluster.origin, cluster.angle) for p in polygon]
            for polygon in _polygons(key, spacing, shrink=shrink)
        ]

    def _radius(key: PlacedKey) -> float:
        return math.hypot(key.width + 0.5, key.height) / 2 * max(spacing)

    if math.dist(k1.switch.position, k2.switch.position) > _radius(k1) + _radius(k2):
        return False
    return any(not _separated(a, b) for a in _global(k1) for b in _global(k2))


def find_layout_options(
    keys: List[PlacedKey],
    clusters: List[Cluster],
    spacing: Tuple[float, float],
) -> None:
    """Group overlapping keys into layout options. Within each group keys are
    assigned to the lowest choice which does not overlap with any key
    already assigned to it (in reference order, so `SW1` would be default
    and `SW1a` would be alternative)."""
    for key in keys:
        key.option = None
    neighbours: Dict[int, Set[int]] = defaultdict(set)
    for i, k1 in enumerate(keys):
        for j in range(i + 1, len(keys)):
            if keys_overlap(k1, keys[j], clusters, spacing):
                neighbours[i].add(j)
                neighbours[j].add(i)

    visited: Set[int] = set()
    groups: List[List[int]] = []
    for i in range(len(keys)):
        if i in visited or i not in neighbours:
            continue
        stack, component = [i], []
        visited.add(i)
        while stack:
            current = stack.pop()
            component.append(current)
            for n in neighbours[current]:
                if n not in visited:
                    visited.add(n)
                    stack.append(n)
        groups.append(sorted(component))

    def _anchor(component: List[int]) -> Tuple[float, float]:
        return min(
            (keys[i].switch.position[1], keys[i].switch.position[0]) for i in component
        )

    groups.sort(key=_anchor)
    for group_index, component in enumerate(groups):
        choices: List[List[int]] = []
        for i in component:  # already in reference order
            for choice_index, members in enumerate(choices):
                if not any(m in neighbours[i] for m in members):
                    members.append(i)
                    keys[i].option = (group_index, choice_index)
                    break
            else:
                choices.append([i])
                keys[i].option = (group_index, len(choices) - 1)
        logger.info(
            f"Layout option {group_index}: "
            + " | ".join(
                ",".join(keys[i].switch.reference for i in members)
                for members in choices
            )
        )


def infer_widths(
    keys: List[PlacedKey], clusters: List[Cluster], spacing: Tuple[float, float]
) -> None:
    """Fit key widths between neighbours for keys which widths are unknown"""
    for cluster_index in range(len(clusters)):
        members = [
            k
            for k in keys
            if k.cluster == cluster_index and (k.option is None or k.option[1] == 0)
        ]
        if not members:
            continue
        left_bound = min(
            k.center_u[0] - (k.width if len(k.allowed_widths) == 1 else 1) / 2
            for k in members
        )
        candidates = [k for k in members if not k.iso and not k.vertical]
        _restrict_by_obstacles(candidates, keys, clusters, spacing)
        for row in _split_rows(candidates):
            if all(len(k.allowed_widths) == 1 for k in row):
                for k in row:
                    k.width = k.allowed_widths[0]
                continue
            widths = solve_row_widths(row, left_bound)
            if widths is None:
                logger.warning(
                    "Could not fit key widths in row with "
                    + ", ".join(k.switch.reference for k in row)
                )
                continue
            for k, w in zip(row, widths):
                k.width = w

    _detect_iso_enter(keys)

    # alternative keys are fitted within the span of default keys of the
    # same layout option group
    for choices in _group_options(keys).values():
        defaults = choices.get(0, [])
        for choice, members in choices.items():
            if choice == 0:
                continue
            for row in _split_rows(
                [k for k in members if not k.iso and not k.vertical]
            ):
                if all(len(k.allowed_widths) == 1 for k in row):
                    continue
                y = row[0].center_u[1]
                span = [
                    d
                    for d in defaults
                    if d.cluster == row[0].cluster
                    and abs(d.center_u[1] - y) < (d.height + 1) / 2 - EPS
                ]
                widths = None
                if span:
                    left = min(d.center_u[0] - d.width / 2 for d in span)
                    right = max(d.center_u[0] + d.width / 2 for d in span)
                    widths = solve_row_widths(row, left, right)
                for i, k in enumerate(row):
                    k.width = widths[i] if widths else k.allowed_widths[0]


def _detect_iso_enter(keys: List[PlacedKey]) -> None:
    """Vertical 2U keys which footprint name does not reveal shape, are
    assumed to be ISO Enter if neighbouring keys touch ISO Enter outline"""

    def _left_edge_neighbour(key: PlacedKey, y: float) -> Optional[float]:
        edges = [
            o.center_u[0] + o.width / 2
            for o in keys
            if o is not key
            and o.cluster == key.cluster
            and (o.option is None or o.option[1] == 0)
            and not o.vertical
            and abs(o.center_u[1] - y) < 0.1
            and o.center_u[0] < key.center_u[0]
        ]
        return max(edges) if edges else None

    for key in keys:
        if not key.vertical or key.height != 2 or key.switch.vertical_name:
            continue
        if key.switch.stabilizer is None:
            continue
        if key.option is not None and key.option[1] != 0:
            continue
        x, y = key.center_u
        top = _left_edge_neighbour(key, y - 0.5)
        bottom = _left_edge_neighbour(key, y + 0.5)
        if (
            top is not None
            and bottom is not None
            and abs(top - (x - 0.875)) < EPS
            and abs(bottom - (x - 0.625)) < EPS
        ):
            logger.info(f"Assuming {key.switch.reference} is ISO Enter")
            key.iso = True
            key.width = 1.25
            key.allowed_widths = [1.25]


def _restrict_by_obstacles(
    candidates: List[PlacedKey],
    keys: List[PlacedKey],
    clusters: List[Cluster],
    spacing: Tuple[float, float],
) -> None:
    """Remove widths which would make key overlap with keys of other rows
    or clusters (e.g. in column staggered layouts gap between keys in a row
    is often occupied by a key which is slightly offset vertically)"""
    for key in candidates:
        if len(key.allowed_widths) == 1:
            continue
        others = [
            o
            for o in keys
            if o is not key
            and (o.option is None or o.option[1] == 0)
            and not (
                o.cluster == key.cluster and abs(o.center_u[1] - key.center_u[1]) < 0.1
            )
        ]
        original = key.width
        allowed = []
        for w in key.allowed_widths:
            key.width = w
            if not any(keys_overlap(key, o, clusters, spacing) for o in others):
                allowed.append(w)
        key.width = original
        key.allowed_widths = allowed or [min(key.allowed_widths)]


def _split_rows(keys: List[PlacedKey]) -> List[List[PlacedKey]]:
    rows: List[List[PlacedKey]] = []
    for key in sorted(keys, key=lambda k: (k.cluster, k.center_u[1])):
        if (
            rows
            and rows[-1][0].cluster == key.cluster
            and abs(rows[-1][0].center_u[1] - key.center_u[1]) < 0.1
        ):
            rows[-1].append(key)
        else:
            rows.append([key])
    for row in rows:
        row.sort(key=lambda k: k.center_u[0])
    return rows


def _int_if_integral(value: float) -> float:
    return int(value) if float(value).is_integer() else value


def _snap(value: float, opts: Options) -> float:
    if opts.grid:
        snapped = round(value / opts.grid) * opts.grid
        if abs(snapped - value) <= opts.grid_tolerance:
            value = snapped
    return _int_if_integral(round(value, PRECISION) + 0.0)


def _snap_angle(angle: float) -> float:
    if abs(angle - round(angle)) < 1e-3:
        angle = round(angle)
    return _int_if_integral(round(angle, PRECISION) + 0.0)


def _key_corners(
    key: PlacedKey, clusters: List[Cluster], spacing: Tuple[float, float]
) -> List[Tuple[float, float]]:
    """Global key corners in key units"""
    sx, sy = spacing
    cluster = clusters[key.cluster]
    result = []
    for x, y, w, h in _key_rects(key):
        for cx, cy in [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]:
            point = (key.local[0] + cx * sx, key.local[1] + cy * sy)
            if cluster.angle:
                # rotation is done in mm space, same as kbplacer does
                point = rotate_point(point, cluster.origin, cluster.angle)
            result.append((point[0] / sx, point[1] / sy))
    return result


def compute_shift(
    keys: List[PlacedKey], clusters: List[Cluster], spacing: Tuple[float, float]
) -> Tuple[float, float]:
    """Translation (in key units) which moves top-left corner of non-rotated
    keys to (0, 0). If rotated keys stick out, shift is extended by
    multiple of 0.25U to keep non-rotated keys aligned to grid"""
    main_keys = [k for k in keys if k.option is None or k.option[1] == 0]
    straight = [k for k in main_keys if clusters[k.cluster].angle == 0]
    reference = straight or main_keys or keys
    corners = {id(k): _key_corners(k, clusters, spacing) for k in keys}
    shift_x = min(p[0] for k in reference for p in corners[id(k)])
    shift_y = min(p[1] for k in reference for p in corners[id(k)])
    min_x = min(p[0] for k in main_keys for p in corners[id(k)])
    min_y = min(p[1] for k in main_keys for p in corners[id(k)])
    if min_x < shift_x - EPS:
        shift_x -= math.ceil((shift_x - min_x) / 0.25) * 0.25
    if min_y < shift_y - EPS:
        shift_y -= math.ceil((shift_y - min_y) / 0.25) * 0.25
    return shift_x, shift_y


def _set_cluster_origin(
    keys: List[PlacedKey],
    clusters: List[Cluster],
    index: int,
    origin: Tuple[float, float],
    spacing: Tuple[float, float],
) -> None:
    cluster = clusters[index]
    for key in keys:
        if key.cluster == index:
            center = rotate_point(key.local, cluster.origin, cluster.angle)
            key.local = rotate_point(center, origin, -cluster.angle)
            key.center_u = (key.local[0] / spacing[0], key.local[1] / spacing[1])
    cluster.origin = origin


def optimize_cluster_origins(
    keys: List[PlacedKey],
    clusters: List[Cluster],
    spacing: Tuple[float, float],
    shift: Tuple[float, float],
    opts: Options,
) -> None:
    """Rotation origin can be chosen freely, search for one (on 0.25U grid)
    for which rotated keys positions are aligned to the grid, this is most
    likely the origin used by layout author"""
    sx, sy = spacing
    step = 0.25
    for index, cluster in enumerate(clusters):
        if not cluster.angle:
            continue
        members = [k for k in keys if k.cluster == index]
        centers = [
            rotate_point(k.local, cluster.origin, cluster.angle) for k in members
        ]
        xs = [c[0] / sx - shift[0] for c in centers]
        ys = [c[1] / sy - shift[1] for c in centers]
        margin = 4
        x_range = range(
            math.floor((min(xs) - margin) / step), math.ceil((max(xs) + margin) / step)
        )
        y_range = range(
            math.floor((min(ys) - margin) / step), math.ceil((max(ys) + margin) / step)
        )

        def _on_grid(value: float) -> bool:
            return abs(value / opts.grid - round(value / opts.grid)) * opts.grid <= (
                opts.grid_tolerance
            )

        first = (xs[0], ys[0])
        best = None
        for i in x_range:
            for j in y_range:
                gx, gy = i * step, j * step
                origin = ((gx + shift[0]) * sx, (gy + shift[1]) * sy)
                score = 0
                for key, center in zip(members, centers):
                    u = rotate_point(center, origin, -cluster.angle)
                    x = u[0] / sx - shift[0] - key.width / 2
                    y = u[1] / sy - shift[1] - key.height / 2
                    score += _on_grid(x) + _on_grid(y)
                coarseness = (
                    (gx % 1 != 0) + (gy % 1 != 0) + (gx % 0.5 != 0) + (gy % 0.5 != 0)
                )
                rank = (-score, coarseness, math.dist((gx, gy), first))
                if best is None or rank < best[0]:
                    best = (rank, origin)
        if best and best[0][0] < 0:
            _set_cluster_origin(keys, clusters, index, best[1], spacing)


def create_keyboard(
    keys: List[PlacedKey],
    clusters: List[Cluster],
    spacing: Tuple[float, float],
    opts: Options,
    matrix: Dict[str, Tuple[str, str]],
) -> Keyboard:
    sx, sy = spacing
    origins_u = [(c.origin[0] / sx, c.origin[1] / sy) for c in clusters]
    main_keys = [k for k in keys if k.option is None or k.option[1] == 0]
    alternatives = [k for k in keys if k.option is not None and k.option[1] != 0]
    shift_x, shift_y = compute_shift(keys, clusters, spacing)

    def _make_key(key: PlacedKey, offset_y: float = 0) -> Key:
        result = Key()
        result.width = _int_if_integral(key.width)
        result.height = _int_if_integral(key.height)
        if key.iso:
            result.width2, result.height2 = 1.5, 1
            result.x2 = -0.25
        else:
            result.width2, result.height2 = result.width, result.height
        cluster = clusters[key.cluster]
        if cluster.angle:
            result.rotation_angle = _snap_angle(cluster.angle)
            result.rotation_x = _snap(origins_u[key.cluster][0] - shift_x, opts)
            # displaced alternative keys keep rotation origin, kbplacer's
            # layout collapsing moves keys by x/y only
            result.rotation_y = _snap(origins_u[key.cluster][1] - shift_y, opts)
        result.x = _snap(key.center_u[0] - key.width / 2 - shift_x, opts)
        result.y = _snap(key.center_u[1] - key.height / 2 - shift_y + offset_y, opts)
        if key.switch_rotation:
            result.switchRotation = _int_if_integral(key.switch_rotation)
        if key.encoder:
            result.sm = "rot_ec11"
        reference = key.switch.reference
        if opts.matrix_labels and reference in matrix:
            row, column = matrix[reference]
            result.set_label(MATRIX_COORDINATES_LABEL, f"{row},{column}")
        if opts.matrix_labels and key.option is not None:
            group, choice = key.option
            result.set_label(LAYOUT_OPTION_LABEL, f"{group},{choice}")
        if opts.explicit_annotation:
            result.set_label(EXPLICIT_ANNOTATION_LABEL, key.switch.annotation)
        return result

    result_keys = [_make_key(k) for k in main_keys]
    result_keys.sort(
        key=lambda k: (
            k.rotation_angle != 0,
            k.rotation_angle,
            k.rotation_y,
            k.rotation_x,
            k.y,
            k.x,
        )
    )

    # alternative layout choices are placed below the main layout,
    # each (group, choice) pair in separate block, VIA style
    if alternatives and opts.matrix_labels:
        alternatives += _complete_layout_options(keys, clusters, spacing)
        _check_layout_options_anchors(keys + alternatives)
    if alternatives:
        by_option: Dict[Tuple[int, int], List[PlacedKey]] = defaultdict(list)
        for key in alternatives:
            by_option[key.option].append(key)  # type: ignore
        bottom = max(k.y + k.height for k in result_keys) if result_keys else 0
        for option in sorted(by_option):
            members = by_option[option]
            offset_y = 0.0
            if opts.matrix_labels and not opts.alternatives_in_place:
                top = min(k.center_u[1] - k.height / 2 - shift_y for k in members)
                offset_y = math.ceil(bottom + 0.5 - top)
            block = [_make_key(k, offset_y) for k in members]
            block.sort(key=lambda k: (k.rotation_angle, k.y, k.x))
            if offset_y:
                bottom = max(k.y + k.height for k in block)
            result_keys.extend(block)

    keyboard = Keyboard(keys=result_keys)
    keyboard.meta.spacing_x = sx
    keyboard.meta.spacing_y = sy
    return keyboard


def _clone_key(key: PlacedKey, **changes: Any) -> PlacedKey:  # noqa: ANN401
    return replace(key, allowed_widths=list(key.allowed_widths), **changes)


def _group_options(keys: List[PlacedKey]) -> Dict[int, Dict[int, List[PlacedKey]]]:
    """Keys of layout options, by group and choice"""
    options: Dict[int, Dict[int, List[PlacedKey]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for key in keys:
        if key.option is not None:
            options[key.option[0]][key.option[1]].append(key)
    return options


def _top_left(key: PlacedKey) -> Tuple[float, float]:
    return (
        round(key.center_u[0] - key.width / 2, 3),
        round(key.center_u[1] - key.height / 2, 3),
    )


def _complete_layout_options(
    keys: List[PlacedKey], clusters: List[Cluster], spacing: Tuple[float, float]
) -> List[PlacedKey]:
    """Layout collapsing aligns top-left keys of each choice with top-left key
    of default choice. Footprints shared by multiple choices exist only once
    on PCB so reconstructed choice might miss its top-left key. In such case
    add copy of non-overlapping key (from other choice) located at default
    choice anchor. Duplicates are removed by layout collapsing"""
    added = []
    for group, choices in _group_options(keys).items():
        if 0 not in choices:
            continue
        anchor = min(_top_left(k) for k in choices[0])
        for choice, members in choices.items():
            if choice == 0 or min(_top_left(k) for k in members) == anchor:
                continue
            candidates = [
                k
                for c in sorted(choices, key=lambda c: (c == 0, c))
                if c != choice
                for k in choices[c]
                if _top_left(k) == anchor
                and k.cluster == members[0].cluster
                and not any(keys_overlap(k, m, clusters, spacing) for m in members)
            ]
            if candidates:
                clone = _clone_key(candidates[0], option=(group, choice))
                logger.debug(
                    f"Adding {clone.switch.reference} to layout option {group} "
                    f"choice {choice}"
                )
                members.append(clone)
                added.append(clone)
    return added


def _check_layout_options_anchors(keys: List[PlacedKey]) -> None:
    for group, choices in _group_options(keys).items():
        anchors = {
            c: min(_top_left(k) for k in members) for c, members in choices.items()
        }
        if 0 in anchors and any(a != anchors[0] for a in anchors.values()):
            logger.warning(
                f"Layout option {group} choices do not share top-left key position, "
                "collapsing this layout would misplace alternative keys"
            )


def reverse_engineer(board: pcbnew.BOARD, opts: Options) -> Keyboard:
    footprints, switch_pattern = find_switch_footprints(board, opts)
    if not footprints:
        msg = (
            "Could not find any key switch footprints, "
            "use `--switch-pattern` or `--switch-footprint-regex` to select them"
        )
        raise RuntimeError(msg)
    switches = collect_switches(footprints, switch_pattern, opts.hybrid_encoders)
    logger.info("Switch footprints: " + ", ".join(s.reference for s in switches))

    keys, clusters = build_placed_keys(switches, opts)
    spacing = opts.key_distance or guess_key_distance(keys)
    logger.info(f"Key distance: {spacing}")

    find_stabilizers(board, switches, switch_pattern, opts, max(spacing))
    board_has_stabilizers = any(s.stabilizer for s in switches)

    for key in keys:
        key.center_u = (key.local[0] / spacing[0], key.local[1] / spacing[1])

    assign_initial_sizes(keys, opts.width_source, board_has_stabilizers)
    find_layout_options(keys, clusters, spacing)
    if opts.width_source in ("auto", "neighbors"):
        infer_widths(keys, clusters, spacing)
        # wider keys may reveal new overlaps (e.g. split space bar options)
        previous = [k.option for k in keys]
        find_layout_options(keys, clusters, spacing)
        if previous != [k.option for k in keys]:
            assign_initial_sizes(keys, opts.width_source, board_has_stabilizers)
            infer_widths(keys, clusters, spacing)

    if opts.hybrid_encoders == "alternative" and any(s.hybrid for s in switches):
        add_hybrid_alternatives(keys)

    if opts.grid:
        shift = compute_shift(keys, clusters, spacing)
        optimize_cluster_origins(keys, clusters, spacing, shift, opts)

    matrix = (
        resolve_matrix_positions(board, switches, opts) if opts.matrix_labels else {}
    )
    if opts.matrix_labels:
        _check_matrix(keys, matrix)
    if opts.explicit_annotation and not all(
        k.switch.annotation.isdigit() for k in keys
    ):
        logger.warning(
            "Not all switch annotations are numeric, kbplacer would ignore "
            "explicit annotation labels"
        )
    return create_keyboard(keys, clusters, spacing, opts, matrix)


def add_hybrid_alternatives(keys: List[PlacedKey]) -> None:
    """Hybrid switch/encoder footprints become layout option with switch as
    default choice and encoder as alternative one"""
    group = max((k.option[0] for k in keys if k.option is not None), default=-1)
    for key in list(keys):
        if not key.switch.hybrid:
            continue
        if key.option is not None:
            logger.warning(
                f"{key.switch.reference} is hybrid switch/encoder footprint "
                "overlapping other keys, using switch only"
            )
            continue
        group += 1
        key.option = (group, 0)
        encoder = _clone_key(key, option=(group, 1), encoder=True)
        keys.insert(keys.index(key) + 1, encoder)
        logger.info(
            f"Layout option {group}: {key.switch.reference} as switch | as encoder"
        )


def _check_matrix(keys: List[PlacedKey], matrix: Dict[str, Tuple[str, str]]) -> None:
    seen: Dict[Tuple[str, str], List[PlacedKey]] = defaultdict(list)
    for key in keys:
        if position := matrix.get(key.switch.reference):
            seen[position].append(key)
    for position, members in seen.items():
        options = {m.option[0] if m.option else None for m in members}
        if len(members) > 1 and (None in options or len(options) > 1):
            logger.warning(
                f"Matrix position {position} is used by multiple non-overlapping "
                "switches: " + ", ".join(m.switch.reference for m in members)
            )


# Footprints used for verification board, only anchor positions matter
# but kbplacer requires matrix pads to exist
_VERIFY_FOOTPRINTS = {
    "switch": ("1", "2"),
    "encoder": ("S1", "S2"),
    "diode": ("1", "2"),
}


@dataclass
class FootprintPose:
    reference: str
    position: Tuple[float, float]  # mm
    orientation: float  # relative to non-rotated key orientation
    encoder: bool
    hybrid: bool = False  # matches both switch and encoder


@dataclass
class Mismatch:
    original: str
    generated: str
    distance: float  # mm
    orientation: bool  # True when orientations are equal
    kind: bool  # True when both are switches or both are encoders
    credit: float


@dataclass
class VerificationResult:
    """Comparison of original board switches with switches of board created
    by kbplacer out of reverse-engineered layout.

    Every original switch earns credit between 0 and 1:
      - 1 when its counterpart is found within tolerance, with equal
        orientation and kind (switch or encoder),
      - linearly less when position is off, down to 0 at match radius
        (half of key distance), beyond that switch is 'missing',
      - halved for orientation mismatch and halved for kind mismatch.
    Score is the sum of credits divided by number of original switches
    plus number of generated switches without counterpart ('extra'),
    so 100% is reached only when both boards match exactly."""

    score: float = 0
    original: int = 0
    generated: int = 0
    exact: int = 0
    offset: Tuple[float, float] = (0, 0)
    max_error: float = 0
    mismatches: List[Mismatch] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    extra: List[str] = field(default_factory=list)
    # footprints recognized as switches by name but excluded by user's
    # selection, informational only, not part of the score
    unselected: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error and self.exact == self.original == self.generated

    def summary(self, limit: int = 20) -> str:
        lines = [f"Verification score: {self.score:.2f}%"]
        if self.error:
            lines.append(f"  failed: {self.error}")
            return "\n".join(lines)
        lines += [
            f"  original switches: {self.original}, "
            f"generated switches: {self.generated}",
            f"  exact matches: {self.exact}, mismatched: {len(self.mismatches)}, "
            f"missing: {len(self.missing)}, extra: {len(self.extra)}",
            f"  origin offset: ({self.offset[0]:.4f}, {self.offset[1]:.4f}) mm, "
            f"max position error of matched switches: {self.max_error:.4f} mm",
        ]
        for m in self.mismatches[:limit]:
            problems = []
            if m.distance:
                problems.append(f"position off by {m.distance:.3f} mm")
            if not m.orientation:
                problems.append("orientation differs")
            if not m.kind:
                problems.append("switch/encoder kind differs")
            lines.append(
                f"  {m.original} ~ {m.generated}: {', '.join(problems)} "
                f"(credit {m.credit:.2f})"
            )
        if len(self.mismatches) > limit:
            lines.append(f"  ... and {len(self.mismatches) - limit} more mismatches")
        if self.missing:
            lines.append("  missing (not recreated): " + ", ".join(self.missing))
        if self.extra:
            lines.append("  extra (not on original board): " + ", ".join(self.extra))
        if self.unselected:
            lines.append(
                "  not selected but looking like switches (not scored): "
                + ", ".join(self.unselected)
            )
        return "\n".join(lines)


def _write_verification_library(directory: str) -> str:
    library = os.path.join(directory, "pcb2layout_verify.pretty")
    os.mkdir(library)
    for name, pads in _VERIFY_FOOTPRINTS.items():
        content = [f'(footprint "{name}" (version 20240108) (generator "pcb2layout")']
        content.append('  (layer "F.Cu")')
        for i, pad in enumerate(pads):
            content.append(
                f'  (pad "{pad}" thru_hole circle (at {2.54 * i} 0) (size 1.5 1.5) '
                '(drill 0.8) (layers "*.Cu" "*.Mask"))'
            )
        content.append(")")
        with open(os.path.join(library, f"{name}.kicad_mod"), "w") as f:
            f.write("\n".join(content) + "\n")
    return library


def verification_layout(keyboard: Keyboard) -> Keyboard:
    """Copy of layout which kbplacer accepts for PCB creation: every key needs
    numeric matrix coordinates, keys without them get unique ones, existing
    ones are renumbered (equal coordinates stay equal, layout collapsing
    relies on that)"""
    result = copy.deepcopy(keyboard)
    rows: Dict[str, int] = {}
    columns: Dict[str, int] = {}
    default_positions: Set[Tuple[int, int]] = set()
    unannotated = []
    for key in result.keys:
        if key.decal:
            continue
        label = key.get_label(MATRIX_COORDINATES_LABEL)
        option = key.get_label(LAYOUT_OPTION_LABEL)
        key.labels = []
        key.textColor = []
        key.textSize = []
        if option:
            key.set_label(LAYOUT_OPTION_LABEL, option)
        parts = str(label).split(",") if label else []
        if len(parts) != 2:
            unannotated.append(key)
            continue
        row = rows.setdefault(parts[0].strip(), len(rows))
        column = columns.setdefault(parts[1].strip(), len(columns))
        if not option and (row, column) in default_positions:
            # kbplacer rejects such layouts, positions can be verified anyway
            logger.warning(
                f"Duplicate matrix position {label} of default layout key, "
                "using unique one for verification"
            )
            unannotated.append(key)
            continue
        if not option:
            default_positions.add((row, column))
        key.set_label(MATRIX_COORDINATES_LABEL, f"{row},{column}")
    row = len(rows)
    for column, key in enumerate(unannotated):
        key.set_label(MATRIX_COORDINATES_LABEL, f"{row},{column}")
    return result


def create_verification_board(
    keyboard: Keyboard,
    opts: Options,
    orientation: float,
) -> pcbnew.BOARD:
    """Create PCB out of layout using kbplacer"""
    with tempfile.TemporaryDirectory(prefix="pcb2layout-") as directory:
        library = _write_verification_library(directory)
        layout_path = os.path.join(directory, "layout.json")
        with open(layout_path, "w", encoding="utf-8") as f:
            f.write(verification_layout(keyboard).to_json())
        builder = BoardBuilder(
            os.path.join(directory, "verify.kicad_pcb"),
            switch_footprint=f"{library}:switch",
            diode_footprint=f"{library}:diode",
            encoder_footprint=f"{library}:encoder",
        )
        board = builder.create_board(layout_path, add_stabilizers=False)
        key_info = ElementInfo(
            "SW{}",
            PositionOption.DEFAULT,
            ElementPosition(0, 0, orientation, Side.FRONT),
            "",
            start_index=1,
        )
        diode_info = ElementInfo(
            "D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, ""
        )
        KeyPlacer(board).run(
            layout_path,
            key_info,
            diode_info,
            additional_elements=[],
            encoder_adjustment=opts.encoder_adjustment,
        )
    return board


def _switch_poses(
    switches: List[Switch], reference: Dict[bool, float]
) -> List[FootprintPose]:
    return [
        FootprintPose(
            reference=s.reference,
            position=s.position,
            orientation=normalize_angle(reference[s.back] - s.orientation),
            encoder=s.encoder,
            hybrid=s.hybrid,
        )
        for s in switches
    ]


def _reference_orientations(switches: List[Switch], opts: Options) -> Dict[bool, float]:
    if opts.switch_orientation is not None:
        return {False: opts.switch_orientation, True: opts.switch_orientation}
    return {back: guess_reference_orientation(switches, back) for back in (False, True)}


class _SpatialIndex:
    def __init__(self, poses: List[FootprintPose], cell: float) -> None:
        self.cell = cell
        self.buckets: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        for i, pose in enumerate(poses):
            self.buckets[self._cell(pose.position)].append(i)

    def _cell(self, point: Tuple[float, float]) -> Tuple[int, int]:
        return math.floor(point[0] / self.cell), math.floor(point[1] / self.cell)

    def near(self, point: Tuple[float, float]) -> Iterable[int]:
        cx, cy = self._cell(point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                yield from self.buckets.get((cx + dx, cy + dy), [])


def estimate_offset(
    original: List[FootprintPose],
    generated: List[FootprintPose],
    tolerance: float,
    samples: int = 30,
) -> Tuple[float, float]:
    """Find translation which moves generated footprints onto original ones.
    Origins of both boards are unrelated and footprint references are not
    comparable, so each pairing of sampled generated footprint with any
    original footprint is a candidate translation, the one which aligns the
    most footprints wins (robust to missing and misplaced footprints)"""
    if not original or not generated:
        return (0, 0)
    loose = max(10 * tolerance, 0.5)
    index = _SpatialIndex(original, loose)
    step = max(1, len(generated) // samples)
    candidates = set()
    for g in generated[::step]:
        for o in original:
            candidates.add(
                (
                    round(o.position[0] - g.position[0], 4),
                    round(o.position[1] - g.position[1], 4),
                )
            )

    def _evaluate(offset: Tuple[float, float]) -> Tuple[int, int, float]:
        exact, close, error = 0, 0, 0.0
        for g in generated:
            point = (g.position[0] + offset[0], g.position[1] + offset[1])
            best = min(
                (math.dist(point, original[i].position) for i in index.near(point)),
                default=math.inf,
            )
            if best <= tolerance:
                exact += 1
            if best <= loose:
                close += 1
                error += best
        return exact, close, -error

    return max(sorted(candidates), key=_evaluate)


def match_footprints(
    original: List[FootprintPose],
    generated: List[FootprintPose],
    offset: Tuple[float, float],
    radius: float,
    tolerance: float,
) -> VerificationResult:
    result = VerificationResult(
        original=len(original), generated=len(generated), offset=offset
    )
    index = _SpatialIndex(original, radius)
    pairs = []
    for j, g in enumerate(generated):
        point = (g.position[0] + offset[0], g.position[1] + offset[1])
        for i in index.near(point):
            o = original[i]
            distance = math.dist(point, o.position)
            if distance > radius:
                continue
            orientation = math.isclose(
                normalize_angle(o.orientation - g.orientation), 0, abs_tol=0.01
            )
            kind = o.hybrid or o.encoder == g.encoder
            pairs.append(
                ((distance > tolerance, not kind, not orientation, distance), i, j)
            )
    pairs.sort()

    used_original: Set[int] = set()
    used_generated: Set[int] = set()
    matches: List[Tuple[int, int]] = []
    credits = 0.0
    for (off, kind_differs, orientation_differs, distance), i, j in pairs:
        if i in used_original or j in used_generated:
            continue
        used_original.add(i)
        used_generated.add(j)
        matches.append((i, j))
        credit = 1.0 if not off else max(0.0, 1 - distance / radius)
        if orientation_differs:
            credit *= 0.5
        if kind_differs:
            credit *= 0.5
        credits += credit
        result.max_error = max(result.max_error, distance)
        if credit == 1.0:
            result.exact += 1
        else:
            result.mismatches.append(
                Mismatch(
                    original=original[i].reference,
                    generated=generated[j].reference,
                    distance=round(distance, 4) if off else 0,
                    orientation=not orientation_differs,
                    kind=not kind_differs,
                    credit=credit,
                )
            )
    # hybrid footprint can be re-created twice, as switch and as encoder
    # (layout option), such second footprint is not an extra one
    kinds: Dict[int, Set[bool]] = defaultdict(set)
    for i, j in matches:
        kinds[i].add(generated[j].encoder)
    for (off, _, orientation_differs, _), i, j in pairs:
        g = generated[j]
        if (
            j in used_generated
            or off
            or orientation_differs
            or not original[i].hybrid
            or g.encoder in kinds[i]
        ):
            continue
        used_generated.add(j)
        kinds[i].add(g.encoder)
    result.mismatches.sort(key=lambda m: natural_key(m.original))
    result.missing = [
        o.reference for i, o in enumerate(original) if i not in used_original
    ]
    result.extra = [
        g.reference for j, g in enumerate(generated) if j not in used_generated
    ]
    total = len(original) + len(result.extra)
    # floor, so anything short of exact match does not round up to 100%
    result.score = math.floor(10000 * credits / total) / 100 if total else 0
    return result


def verify_layout(
    board: pcbnew.BOARD,
    keyboard: Keyboard,
    opts: Options,
    tolerance: float = 0.02,
) -> VerificationResult:
    """Create PCB out of reverse-engineered layout with kbplacer and compare
    its switch footprints with switch footprints of original board"""
    footprints, switch_pattern = find_switch_footprints(board, opts)
    switches = collect_switches(footprints, switch_pattern, opts.hybrid_encoders)
    reference = _reference_orientations(switches, opts)
    original = _switch_poses(switches, reference)

    # generated board has all switches on the front side,
    # orientations are compared relative to reference orientation
    generated_reference = reference[all(s.back for s in switches)]
    try:
        generated_board = create_verification_board(keyboard, opts, generated_reference)
    except Exception as e:  # noqa: BLE001, anything kbplacer may raise
        logger.debug("Verification board creation failed", exc_info=True)
        return VerificationResult(
            original=len(original), error=f"{type(e).__name__}: {e}"
        )
    generated = [
        FootprintPose(
            reference=f.GetReference(),
            position=_position_mm(f),
            orientation=normalize_angle(
                generated_reference - f.GetOrientationDegrees()
            ),
            encoder=_footprint_name(f) == "encoder",
        )
        for f in generated_board.GetFootprints()
        if _footprint_name(f) in ("switch", "encoder")
    ]
    generated.sort(key=lambda p: natural_key(p.reference))

    spacing = (keyboard.meta.spacing_x, keyboard.meta.spacing_y)
    radius = 0.5 * min(spacing)
    offset = estimate_offset(original, generated, tolerance)
    result = match_footprints(original, generated, offset, radius, tolerance)
    if opts.switch_pattern or opts.switch_footprint_regex:
        guessed, _ = find_switch_footprints(board, Options())
        selected = {s.reference for s in switches}
        result.unselected = sorted(
            {f.GetReference() for f in guessed} - selected, key=natural_key
        )
    return result


def to_output(keyboard: Keyboard, output_format: str) -> str:
    if output_format == "internal":
        return keyboard.to_json(indent=2)
    return "[\n" + keyboard.to_kle() + "\n]\n"


class XYAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,  # noqa: ANN401
        option_string: Optional[str] = None,
    ) -> None:
        try:
            x, y = map(float, str(values).replace(",", " ").split())
        except ValueError:
            parser.error(f"{option_string} expects two numeric values, got '{values}'")
        setattr(namespace, self.dest, (x, y))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reverse-engineer KLE keyboard layout from KiCad PCB file",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-i", "--in", required=True, help="Input .kicad_pcb file")
    parser.add_argument(
        "-o", "--out", default="-", help="Output layout file, stdout when omitted"
    )
    parser.add_argument(
        "-f", "--force", action="store_true", help="Overwrite existing output file"
    )
    parser.add_argument(
        "--format",
        default="kle",
        choices=["kle", "internal"],
        help="Output format, KLE raw data or kbplacer internal json, "
        "default=%(default)s",
    )
    parser.add_argument(
        "-s",
        "--switch-pattern",
        default="",
        help=(
            "Switch footprints annotation pattern with '{}' placeholder, e.g. 'SW{}'.\n"
            "When not defined, switches are guessed by footprint names\n"
            "(Cherry MX, Choc, Kailh, Gateron, Alps, encoders...) and then by\n"
            "common reference prefixes (SW, K, KEY, S, MX)"
        ),
    )
    parser.add_argument(
        "--switch-footprint-regex",
        default="",
        help=(
            "Case insensitive regular expression for switch footprint names,\n"
            "e.g. 'MX|Choc'. Can be combined with --switch-pattern"
        ),
    )
    parser.add_argument(
        "--stabilizer-pattern",
        default="",
        help=(
            "Stabilizer annotation pattern, e.g. 'ST{}'.\n"
            "When not defined, footprints with 'stab' in name are used"
        ),
    )
    parser.add_argument(
        "--diode-pattern",
        default="",
        help=(
            "Diode annotation pattern, e.g. 'D{}', used for matrix resolution.\n"
            "When not defined, guessed by reference and footprint name"
        ),
    )
    parser.add_argument(
        "--key-distance",
        default=None,
        action=XYAction,
        help=(
            "X and Y key 1U distance in mm, as two space separated numeric values.\n"
            "Guessed from distances between neighbouring keys when not defined"
        ),
    )
    parser.add_argument(
        "--switch-orientation",
        default=None,
        type=float,
        help=(
            "Orientation (in degrees) of switch footprints of non-rotated keys,\n"
            "same as ORIENTATION of kbplacer's --switch option.\n"
            "When not defined, most common orientation (multiple of 90) is used"
        ),
    )
    parser.add_argument(
        "--encoder-adjustment",
        default=None,
        action=XYAction,
        help=(
            "X and Y adjustment offset of encoder footprints in mm used\n"
            "when PCB was created (see kbplacer's --encoder-adjustment)"
        ),
    )
    parser.add_argument(
        "--hybrid-encoders",
        default="alternative",
        choices=["alternative", "switch", "encoder"],
        help=(
            "How to treat footprints which accept either key switch or encoder\n"
            "(e.g. 'keyswitch_cherrymx_hotswap_1u_rotary_encoder_ec12'):\n"
            "  alternative - switch, with encoder as alternative layout choice,\n"
            "                overlapping it (moved below the layout VIA style\n"
            "                with --matrix-labels, see --alternatives-in-place)\n"
            "  switch      - switch only\n"
            "  encoder     - encoder only\n"
            "default=%(default)s"
        ),
    )
    parser.add_argument(
        "--width-source",
        default="auto",
        choices=["auto", "name", "neighbors", "none"],
        help=(
            "How key sizes are determined:\n"
            "  auto      - footprint name (e.g. '1.50u', 'ISOEnter'), if not\n"
            "              available fit width between neighbouring keys,\n"
            "              using stabilizers as hint\n"
            "  name      - footprint (or stabilizer) name only, 1U otherwise\n"
            "  neighbors - always fit width between neighbouring keys\n"
            "  none      - all keys are 1U\n"
            "default=%(default)s"
        ),
    )
    parser.add_argument(
        "--matrix-labels",
        action="store_true",
        help=(
            "Add via-style 'row,column' labels (top-left label) based on matrix\n"
            "netlist and 'group,choice' layout option labels (bottom-right label)\n"
            "for overlapping keys"
        ),
    )
    parser.add_argument(
        "--row-pattern",
        default="",
        help="Row net name pattern, e.g. 'ROW{}', guessed when not defined",
    )
    parser.add_argument(
        "--column-pattern",
        default="",
        help="Column net name pattern, e.g. 'COL{}', guessed when not defined",
    )
    parser.add_argument(
        "--diode-side",
        default="row",
        choices=["row", "column"],
        help=(
            "Matrix side connected through diodes, used when net names do not\n"
            "reveal rows and columns, default=%(default)s (COL2ROW)"
        ),
    )
    parser.add_argument(
        "--alternatives-in-place",
        action="store_true",
        help=(
            "Keep alternative layout keys at their PCB positions instead of\n"
            "moving them below the layout (VIA style)"
        ),
    )
    parser.add_argument(
        "--explicit-annotation",
        action="store_true",
        help=(
            "Add switch annotation number to label used by kbplacer for\n"
            "explicit annotation (KLE label 10)"
        ),
    )
    parser.add_argument(
        "--grid",
        default=0.125,
        type=float,
        help=(
            "Snap key coordinates (in key units) to this grid when within\n"
            "--grid-tolerance, 0 disables, default=%(default)s"
        ),
    )
    parser.add_argument(
        "--grid-tolerance",
        default=0.0005,
        type=float,
        help="Grid snapping tolerance in key units, default=%(default)s",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Verify result: create PCB out of reverse-engineered layout with\n"
            "kbplacer and compare its switch positions with input PCB.\n"
            "Summary with score (100%% for exact match) is printed to stderr"
        ),
    )
    parser.add_argument(
        "--verify-tolerance",
        default=0.02,
        type=float,
        help="Maximum distance (mm) of matching switches, default=%(default)s",
    )
    parser.add_argument(
        "--verify-min-score",
        default=None,
        type=float,
        help=(
            f"Exit with status {EXIT_LOW_SCORE} when verification score is below\n"
            "this value (implies --verify)"
        ),
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=logging._nameToLevel.keys(),
        help="Provide logging level, default=%(default)s",
    )
    return parser.parse_args(argv)


def load_board(path: str) -> Optional[pcbnew.BOARD]:
    try:
        board = pcbnew.LoadBoard(path)
    except Exception as e:  # noqa: BLE001, pcbnew raises IO_ERROR variants
        logger.debug("Board loading failed", exc_info=True)
        logger.error(f"Could not load {path}: {e}")
        return None
    if board is None:
        logger.error(f"Could not load {path}, not a valid KiCad PCB file")
    return board


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(levelname)s: %(message)s")

    input_path = getattr(args, "in")
    output_path = args.out
    if not os.path.isfile(input_path):
        logger.error(f"File {input_path} does not exist")
        return 1
    if output_path != "-" and os.path.exists(output_path) and not args.force:
        logger.error(f"File {output_path} already exist, use --force to overwrite")
        return 1

    opts = Options(
        switch_pattern=args.switch_pattern,
        switch_footprint_regex=args.switch_footprint_regex,
        diode_pattern=args.diode_pattern,
        stabilizer_pattern=args.stabilizer_pattern,
        key_distance=args.key_distance,
        switch_orientation=args.switch_orientation,
        encoder_adjustment=args.encoder_adjustment,
        hybrid_encoders=args.hybrid_encoders,
        width_source=args.width_source,
        matrix_labels=args.matrix_labels,
        row_pattern=args.row_pattern,
        column_pattern=args.column_pattern,
        diode_side=args.diode_side,
        alternatives_in_place=args.alternatives_in_place,
        explicit_annotation=args.explicit_annotation,
        grid=args.grid,
        grid_tolerance=args.grid_tolerance,
    )

    board = load_board(input_path)
    if board is None:
        return 1
    try:
        keyboard = reverse_engineer(board, opts)
    except (RuntimeError, ValueError) as e:
        logger.error(e)
        return 1

    result = to_output(keyboard, args.format)
    if output_path == "-":
        sys.stdout.write(result)
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result)

    if args.verify or args.verify_min_score is not None:
        verification = verify_layout(board, keyboard, opts, args.verify_tolerance)
        sys.stderr.write(verification.summary() + "\n")
        if (
            args.verify_min_score is not None
            and verification.score < args.verify_min_score
        ):
            return EXIT_LOW_SCORE
    return 0


if __name__ == "__main__":
    sys.exit(main())
