# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import pcbnew

from .kle_serial import Key, is_iso_enter

logger = logging.getLogger(__name__)


def is_valid_template(s: str) -> bool:
    """Check if string is a valid Python format template.

    Tests if string can be formatted with a numeric value and actually uses it.
    """
    try:
        formatted = s.format(1)
        # Check if formatting actually changed the string
        # (i.e., there was a placeholder)
        return formatted != s
    except (ValueError, IndexError, KeyError):
        return False


@dataclass
class FootprintIdentifier:
    """Parses and validates footprint identifier strings.

    Footprint identifiers have the format: library_path:footprint_name
    - library_path: Path to .pretty directory (Unix or Windows style)
    - footprint_name: Footprint name, may contain format string like {:.2f}
    """

    library_path: str
    footprint_name: str

    @classmethod
    def from_str(cls, identifier: str) -> FootprintIdentifier:
        if len(identifier) >= 3 and identifier[1:3] == ":\\":
            # Windows path detected (e.g., C:\path\...)
            # Find the second colon which separates library from footprint name
            second_colon_pos = identifier.find(":", 2)
            if second_colon_pos == -1:
                msg = f"Unexpected footprint value: `{identifier}`"
                raise ValueError(msg)
            library_path = identifier[:second_colon_pos]
            footprint_name = identifier[second_colon_pos + 1 :]
        else:
            # Unix-style path, split on the first colon
            parts = identifier.split(":", 1)
            if len(parts) != 2:
                msg = f"Unexpected footprint value: `{identifier}`"
                raise ValueError(msg)
            library_path, footprint_name = parts

        return cls(library_path=library_path, footprint_name=footprint_name)

    def get_library_name(self) -> str:
        """Extract library name from library path for schematic use.

        Extracts the directory name and removes '.pretty' suffix.

        Examples:
            /usr/share/kicad/footprints/Diode_SMD.pretty -> Diode_SMD
            C:\\kicad\\footprints\\Button_Switch.pretty -> Button_Switch

        Returns:
            Library name without path or .pretty suffix
        """
        # Get the last path component (directory name)
        # Handle both Unix (/) and Windows (\\) path separators
        library_dir = self.library_path.replace("\\", "/").rstrip("/").split("/")[-1]

        # Remove .pretty suffix if present
        if library_dir.endswith(".pretty"):
            library_dir = library_dir[:-7]  # len(".pretty") == 7

        return library_dir

    def format_for_schematic(self, footprint_name: Optional[str] = None) -> str:
        """Format footprint identifier for KiCad schematic symbol.

        KiCad schematics use format: LibraryName:FootprintName
        (without full path, just library name extracted from .pretty directory)

        Args:
            footprint_name: Optional footprint name override. If None, uses self.footprint_name

        Returns:
            Formatted string like "Diode_SMD:D_SOD-123F"
        """
        lib_name = self.get_library_name()
        fp_name = footprint_name if footprint_name is not None else self.footprint_name
        return f"{lib_name}:{fp_name}"


class SwitchFootprintDiscovery:
    """Scans library directory to discover available switch footprints and widths.

    This class lazily scans a footprint library directory to discover:
    - Available footprint width variants
    - ISO Enter footprints
    - Base footprint names

    The scan is performed once on first access and results are cached.
    """

    def __init__(self, library_path: str) -> None:
        self._library_path = library_path
        self._cache: Dict[str, List[float]] = {}
        self._iso_enter_footprints: Set[str] = set()
        self._scanned = False

    def get_available_widths(self, base_footprint_name: str) -> List[float]:
        self._ensure_scanned()
        return sorted(self._cache.get(base_footprint_name, []))

    def get_iso_enter_footprints(self) -> Set[str]:
        self._ensure_scanned()
        return self._iso_enter_footprints.copy()

    def find_closest_width(
        self, base_footprint_name: str, requested_width: float
    ) -> Optional[float]:
        """Find closest available width with fallback to 1.0u.

        Strategy:
        1. If exact match exists, use it
        2. If 1.0u exists, use it as standard fallback
        3. Otherwise use closest available width
        4. If no widths available, return None

        Args:
            base_footprint_name: Base name without width suffix
            requested_width: Desired width in units

        Returns:
            Closest available width, or None if no widths found
        """
        available = self.get_available_widths(base_footprint_name)

        if not available:
            return None

        # Check for exact match
        if requested_width in available:
            return requested_width

        # Fallback to standard 1.0u if available
        if 1.0 in available:
            if requested_width != 1.0:
                logger.warning(
                    f"Requested width {requested_width}u not available for "
                    f"{base_footprint_name}, using 1.0u fallback"
                )
            return 1.0

        # Find closest width
        closest = min(available, key=lambda x: abs(x - requested_width))
        logger.warning(
            f"Requested width {requested_width}u not available for "
            f"{base_footprint_name}, using closest: {closest}u"
        )
        return closest

    def _ensure_scanned(self) -> None:
        """Ensure library has been scanned (lazy initialization)."""
        if not self._scanned:
            self._scan_library()
            self._scanned = True

    def _parse_filename(self, filename: str) -> Optional[Tuple[str, float]]:
        """Parse footprint filename to extract base name and width.

        Expected pattern: {base_name}_{width}u.kicad_mod
        Example: SW_Cherry_MX_PCB_1.50u.kicad_mod -> ("SW_Cherry_MX_PCB", 1.5)

        Args:
            filename: Footprint filename

        Returns:
            Tuple of (base_name, width) or None if pattern doesn't match
        """
        # Match pattern: anything followed by underscore, digits/dots, 'u.kicad_mod'
        match = re.match(r"^(.+?)_([\d.]+)u\.kicad_mod$", filename)
        if match:
            base_name = match.group(1)
            try:
                width = float(match.group(2))
                return (base_name, width)
            except ValueError:
                return None
        return None

    def _scan_library(self) -> None:
        """Scan library directory and populate cache.

        Reads all .kicad_mod files in the library directory and:
        - Extracts width variants for each footprint family
        - Identifies ISO Enter footprints
        """
        if not os.path.isdir(self._library_path):
            logger.warning(f"Library directory not found: {self._library_path}")
            return

        try:
            files = os.listdir(self._library_path)
        except OSError as e:
            logger.warning(
                f"Failed to read library directory {self._library_path}: {e}"
            )
            return

        footprint_count = 0
        for filename in files:
            if not filename.endswith(".kicad_mod"):
                continue

            footprint_count += 1

            # Check for ISO Enter footprints
            if "iso" in filename.lower() or "isoenter" in filename.lower():
                # Remove .kicad_mod extension
                footprint_name = filename[:-10]
                self._iso_enter_footprints.add(footprint_name)

            # Parse width variants
            parsed = self._parse_filename(filename)
            if parsed:
                base_name, width = parsed
                if base_name not in self._cache:
                    self._cache[base_name] = []
                self._cache[base_name].append(width)

        logger.debug(
            f"Scanned library {self._library_path}: "
            f"{footprint_count} footprints, "
            f"{len(self._cache)} width variant families, "
            f"{len(self._iso_enter_footprints)} ISO Enter footprints"
        )


class SwitchFootprintLoader:
    """Main interface for loading switch footprints with variable width support.

    This loader is specifically designed for switches and provides:
    - Parsing footprint identifiers with template support
    - Discovering available widths from library
    - Fallback to 1.0u when requested width unavailable
    - ISO Enter special case handling
    - Loading footprints via pcbnew API

    Note: For diodes and other non-switch footprints, use FootprintIdentifier
    directly with pcbnew.FootprintLoad().
    """

    def __init__(self, identifier_str: str) -> None:
        """Initialize switch footprint loader.

        Args:
            identifier_str: Footprint identifier in format "library:name"
                          May contain format template like "lib:SW_{:.2f}u"

        Raises:
            ValueError: If identifier format is invalid
        """
        self.identifier = FootprintIdentifier.from_str(identifier_str)
        self._discovery: Optional[SwitchFootprintDiscovery] = None

    def load(self, key: Optional[Key] = None) -> pcbnew.FOOTPRINT:
        """Load footprint for given key.

        Logic:
        1. Check if key is ISO Enter and use dedicated footprint if available
        2. If identifier is template, discover and use appropriate width
        3. Load footprint using pcbnew.FootprintLoad()

        Args:
            key: Optional Key object for width and ISO Enter detection
                 If None, uses 1.0u width

        Returns:
            Loaded footprint

        Raises:
            RuntimeError: If footprint cannot be loaded
        """
        footprint_name = self.get_footprint_name(key=key)
        fp = pcbnew.FootprintLoad(self.identifier.library_path, footprint_name)

        if fp is None:
            msg = (
                f"Unable to load footprint: "
                f"{self.identifier.library_path}:{footprint_name}"
            )
            raise RuntimeError(msg)

        return fp

    def _format(self, width: float) -> str:
        if is_valid_template(self.identifier.footprint_name):
            return self.identifier.footprint_name.format(width)
        return self.identifier.footprint_name

    def get_footprint_name(self, key: Optional[Key] = None) -> str:
        """Get footprint name that will be loaded (without actually loading it).

        Useful for:
        - Validation
        - Setting footprint property in schematics
        - Testing

        Args:
            key: Optional Key object for width and ISO Enter detection
                 If None, uses 1.0u width

        Returns:
            Footprint name that will be used
        """
        # Extract width from key, default to 1.0u
        width = key.width if key else 1.0

        # Handle template footprints
        if is_valid_template(self.identifier.footprint_name):
            # Check for ISO Enter special case
            if key and is_iso_enter(key):
                iso_footprints = self._get_discovery().get_iso_enter_footprints()
                if iso_footprints:
                    # Use first ISO Enter footprint found
                    iso_footprint = next(iter(iso_footprints))
                    logger.debug(f"Using ISO Enter footprint: {iso_footprint}")
                    return iso_footprint

            base_name = self._extract_base_name_from_template()
            if base_name:
                closest_width = self._get_discovery().find_closest_width(
                    base_name, width
                )
                if closest_width is not None:
                    return self._format(closest_width)
                else:
                    # No widths found in library, use requested width
                    # Log as debug instead of warning since template might be valid
                    # but we just don't have the files locally
                    logger.debug(
                        f"No width variants found for {base_name} in library, "
                        f"using requested width {width}u"
                    )
                    return self._format(width)

            # Couldn't extract base name, just format with width
            return self._format(width)

        # Non-template footprint, return as-is
        return self.identifier.footprint_name

    def get_footprint_for_schematic(self, key: Optional[Key] = None) -> str:
        """Get footprint identifier formatted for KiCad schematic symbol.

        Combines library name (extracted from path) with footprint name.
        Format: LibraryName:FootprintName

        Args:
            key: Optional Key object for width and ISO Enter detection
                 If None, uses 1.0u width

        Returns:
            Formatted string like "Button_Switch_Keyboard:SW_Cherry_MX_PCB_1.00u"
        """
        footprint_name = self.get_footprint_name(key=key)
        return self.identifier.format_for_schematic(footprint_name)

    def _get_discovery(self) -> SwitchFootprintDiscovery:
        """Get or create FootprintDiscovery instance (lazy initialization).

        Returns:
            FootprintDiscovery instance for this library
        """
        if self._discovery is None:
            self._discovery = SwitchFootprintDiscovery(self.identifier.library_path)
        return self._discovery

    def _extract_base_name_from_template(self) -> Optional[str]:
        """Extract base footprint name from template string.

        Removes the format placeholder and width suffix to get base name.
        Example: "SW_Cherry_MX_PCB_{:.2f}u" -> "SW_Cherry_MX_PCB"

        Returns:
            Base name or None if extraction fails
        """
        template = self.identifier.footprint_name

        # Try to extract base name by removing format placeholder
        # Common patterns:
        # - "base_{:.2f}u" -> "base"
        # - "base_{}u" -> "base"
        # - "base_{:f}u" -> "base"

        # Match patterns like: base_{format}u
        match = re.match(r"^(.+?)_\{[^}]*\}u$", template)
        if match:
            return match.group(1)

        # Couldn't extract, try formatting with 1.0 and removing suffix
        try:
            formatted = template.format(1.0)
            # Remove _1.00u or similar suffix
            match = re.match(r"^(.+?)_[\d.]+u$", formatted)
            if match:
                return match.group(1)
        except (ValueError, IndexError, KeyError):
            pass

        logger.warning(f"Could not extract base name from template: {template}")
        return None
