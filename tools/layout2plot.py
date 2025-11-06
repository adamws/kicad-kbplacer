# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import yaml

from kbplacer.kle_serial import Keyboard, MatrixAnnotatedKeyboard, get_keyboard

logger = logging.getLogger(__name__)


def create_plot(
    input_path: str,
    output_path: str,
    rect_width: float,
    rect_height: float,
    ignore_alternative: bool = False,
):
    """
    Create a matplotlib plot showing rectangles at each key position from a KLE layout file.

    :param input_path: Path to input KLE layout file (JSON or YAML)
    :param output_path: Path to output plot file (PNG, PDF, SVG, etc.)
    :param rect_width: Width of each rectangle in the layout units
    :param rect_height: Height of each rectangle in the layout units
    :param ignore_alternative: Ignore alternative layout keys
    """
    # Load layout file
    if input_path != "-":
        with open(input_path, "r", encoding="utf-8") as f:
            if input_path.endswith("yaml") or input_path.endswith("yml"):
                layout = yaml.safe_load(f)
            else:
                layout = json.load(f)
    else:
        try:
            layout = yaml.safe_load(sys.stdin)
        except Exception:
            layout = json.load(sys.stdin)

    keyboard: Keyboard = get_keyboard(layout)

    # Create figure and axis
    fig, ax = plt.subplots(1, 1, figsize=(12, 8))
    ax.set_aspect('equal')

    # Get the appropriate key iterator
    if isinstance(keyboard, MatrixAnnotatedKeyboard):
        keys = keyboard.key_iterator(ignore_alternative=ignore_alternative)
    else:
        keys = iter(keyboard.keys)

    # Process each key in the layout
    for key in keys:
        # Calculate center position of the key
        center_x = key.x + key.width / 2
        center_y = key.y + key.height / 2

        # Calculate bottom-left corner of the rectangle to be drawn
        # (centered at the key position)
        rect_x = center_x - rect_width / 2
        rect_y = center_y - rect_height / 2

        # Create rectangle
        rect = patches.Rectangle(
            (rect_x, rect_y),
            rect_width,
            rect_height,
            linewidth=1,
            edgecolor='black',
            facecolor='lightgray',
            alpha=0.7
        )

        # Apply rotation if needed
        if key.rotation_angle != 0:
            # Calculate rotation in matplotlib (counter-clockwise in degrees)
            angle_deg = key.rotation_angle

            # Get rotation origin
            rot_origin_x = key.rotation_x
            rot_origin_y = key.rotation_y

            # Create transformation: rotate around rotation origin
            # First translate to origin, then rotate, then translate back
            t = plt.matplotlib.transforms.Affine2D()
            t = t.translate(-rot_origin_x, -rot_origin_y)
            t = t.rotate_deg(angle_deg)
            t = t.translate(rot_origin_x, rot_origin_y)

            # Apply transformation to the rectangle
            rect.set_transform(t + ax.transData)

        ax.add_patch(rect)

        # Optionally, mark the center point for debugging
        if key.rotation_angle != 0:
            # Transform the center point for rotated keys
            t = plt.matplotlib.transforms.Affine2D()
            t = t.translate(-key.rotation_x, -key.rotation_y)
            t = t.rotate_deg(key.rotation_angle)
            t = t.translate(key.rotation_x, key.rotation_y)
            transform = t + ax.transData
            ax.plot(center_x, center_y, 'r.', markersize=3, transform=transform)
        else:
            ax.plot(center_x, center_y, 'r.', markersize=3)

    # Set axis labels and invert y-axis (to match KLE coordinate system)
    ax.set_xlabel('X (layout units)')
    ax.set_ylabel('Y (layout units)')
    ax.invert_yaxis()

    # Add grid for reference
    ax.grid(True, alpha=0.3)
    ax.set_title(f'Keyboard Layout Visualization\nRectangle size: {rect_width} x {rect_height}')

    # Auto-scale to fit all rectangles
    ax.autoscale()

    # Save the plot
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    logger.info(f"Plot saved to {output_path}")
    plt.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create a 2D plot of keyboard layout with rectangles at each key position"
    )
    parser.add_argument(
        "-i",
        "--in",
        nargs="?",
        type=str,
        default="-",
        help="Input path to KLE layout file (JSON or YAML) or '-' for stdin",
    )
    parser.add_argument(
        "-o",
        "--out",
        required=True,
        help="Output path for plot file (e.g., plot.png, plot.pdf, plot.svg)",
    )
    parser.add_argument(
        "-w",
        "--width",
        type=float,
        required=True,
        help="Width of rectangle in layout units",
    )
    parser.add_argument(
        "-t",
        "--height",
        type=float,
        required=True,
        help="Height of rectangle in layout units",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Override output if already exists",
    )
    parser.add_argument(
        "--ignore-alternative-layouts",
        action="store_true",
        help="Ignore alternative layout keys",
    )
    parser.add_argument(
        "--log-level",
        required=False,
        default="WARNING",
        choices=logging._nameToLevel.keys(),
        type=str,
        help="Provide logging level, default=%(default)s",
    )

    args = parser.parse_args()
    input_path = getattr(args, "in")
    output_path = getattr(args, "out")
    rect_width = args.width
    rect_height = args.height
    force = args.force

    # Set up logger
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s: %(message)s", datefmt="%H:%M:%S"
    )

    if not force and Path(output_path).is_file():
        logger.error(f"Output file '{output_path}' already exists, use --force to override")
        sys.exit(1)

    create_plot(
        input_path, output_path, rect_width, rect_height, args.ignore_alternative_layouts
    )
