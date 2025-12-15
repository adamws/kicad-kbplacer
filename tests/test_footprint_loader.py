# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path

import pytest

from kbplacer.footprint_loader import (
    FootprintIdentifier,
    SwitchFootprintDiscovery,
    SwitchFootprintLoader,
    is_iso_enter,
    is_valid_template,
)
from kbplacer.kle_serial import Key


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_is_valid_template_with_format_placeholder(self) -> None:
        assert is_valid_template("SW_Cherry_MX_PCB_{:.2f}u")
        assert is_valid_template("footprint_{}u")
        assert is_valid_template("switch_{:f}")

    def test_is_valid_template_without_placeholder(self) -> None:
        assert not is_valid_template("SW_Cherry_MX_PCB_1.00u")
        assert not is_valid_template("simple_footprint")

    def test_is_valid_template_with_invalid_placeholder(self) -> None:
        # These should return False because format will fail
        assert not is_valid_template("SW_{invalid}u")
        assert not is_valid_template("SW_{:.2f")  # Missing closing brace

    def test_is_iso_enter_with_iso_enter_key(self) -> None:
        key = Key(width=1.25, height=2, width2=1.5, height2=1)
        assert is_iso_enter(key)

    def test_is_iso_enter_with_regular_key(self) -> None:
        key = Key(width=1.0, height=1.0, width2=1.0, height2=1.0)
        assert not is_iso_enter(key)

    def test_is_iso_enter_with_different_sizes(self) -> None:
        # 2u key (not ISO Enter)
        key = Key(width=2.0, height=1.0)
        assert not is_iso_enter(key)

        # 1.25u key (not ISO Enter - wrong height)
        key = Key(width=1.25, height=1.0)
        assert not is_iso_enter(key)


class TestFootprintIdentifier:
    """Tests for FootprintIdentifier class."""

    def test_parse_unix_path(self) -> None:
        identifier = FootprintIdentifier.from_str(
            "/path/to/library.pretty:SW_Cherry_MX_PCB_1.00u"
        )
        assert identifier.library_path == "/path/to/library.pretty"
        assert identifier.footprint_name == "SW_Cherry_MX_PCB_1.00u"

    def test_parse_windows_path(self) -> None:
        identifier = FootprintIdentifier.from_str(
            "C:\\Users\\test\\library.pretty:SW_Cherry_MX_PCB_1.00u"
        )
        assert identifier.library_path == "C:\\Users\\test\\library.pretty"
        assert identifier.footprint_name == "SW_Cherry_MX_PCB_1.00u"

    def test_parse_windows_path_with_forward_slash(self) -> None:
        # Windows path but with forward slashes after drive letter
        identifier = FootprintIdentifier.from_str(
            "C:\\path/to/library.pretty:SW_Cherry_MX_PCB_1.00u"
        )
        assert identifier.library_path == "C:\\path/to/library.pretty"
        assert identifier.footprint_name == "SW_Cherry_MX_PCB_1.00u"

    def test_parse_invalid_no_colon(self) -> None:
        with pytest.raises(ValueError, match="Unexpected footprint value"):
            FootprintIdentifier.from_str("invalid_identifier")

    def test_parse_invalid_windows_path_no_second_colon(self) -> None:
        # Looks like Windows path but missing the footprint separator
        with pytest.raises(ValueError, match="Unexpected footprint value"):
            FootprintIdentifier.from_str("C:\\path\\library.pretty")


class TestFootprintDiscovery:
    """Tests for FootprintDiscovery class."""

    @pytest.fixture
    def temp_library(self, tmpdir) -> Path:
        """Create temporary library directory with test footprints."""
        lib_path = Path(tmpdir) / "test.pretty"
        lib_path.mkdir()

        # Create various footprint files
        footprints = [
            "SW_Cherry_MX_PCB_1.00u.kicad_mod",
            "SW_Cherry_MX_PCB_1.50u.kicad_mod",
            "SW_Cherry_MX_PCB_1.75u.kicad_mod",
            "SW_Cherry_MX_PCB_2.00u.kicad_mod",
            "SW_Kailh_1.00u.kicad_mod",
            "SW_Kailh_1.50u.kicad_mod",
            "SW_ISO_Enter.kicad_mod",
            "D_SOD-323.kicad_mod",  # Non-width variant
            "README.md",  # Non-footprint file
        ]

        for fp in footprints:
            (lib_path / fp).touch()

        return lib_path

    def test_parse_filename_valid(self) -> None:
        discovery = SwitchFootprintDiscovery("/dummy")

        result = discovery._parse_filename("SW_Cherry_MX_PCB_1.50u.kicad_mod")
        assert result == ("SW_Cherry_MX_PCB", 1.5)

        result = discovery._parse_filename("SW_Kailh_2.00u.kicad_mod")
        assert result == ("SW_Kailh", 2.0)

        result = discovery._parse_filename("switch_1.00u.kicad_mod")
        assert result == ("switch", 1.0)

    def test_parse_filename_invalid(self) -> None:
        discovery = SwitchFootprintDiscovery("/dummy")

        # Non-footprint file
        assert discovery._parse_filename("README.md") is None

        # Missing width suffix
        assert discovery._parse_filename("SW_Cherry_MX_PCB.kicad_mod") is None

        # Wrong extension
        assert discovery._parse_filename("SW_Cherry_MX_PCB_1.00u.txt") is None

        # Invalid width
        assert (
            discovery._parse_filename("SW_Cherry_MX_PCB_invalidwidth.kicad_mod") is None
        )

    def test_scan_library(self, temp_library) -> None:
        discovery = SwitchFootprintDiscovery(str(temp_library))
        discovery._scan_library()

        # Check cache was populated
        assert "SW_Cherry_MX_PCB" in discovery._cache
        assert "SW_Kailh" in discovery._cache
        assert "D_SOD-323" not in discovery._cache  # Not a width variant

    def test_get_available_widths(self, temp_library) -> None:
        discovery = SwitchFootprintDiscovery(str(temp_library))

        widths = discovery.get_available_widths("SW_Cherry_MX_PCB")
        assert widths == [1.0, 1.5, 1.75, 2.0]

        widths = discovery.get_available_widths("SW_Kailh")
        assert widths == [1.0, 1.5]

        # Non-existent footprint
        widths = discovery.get_available_widths("NonExistent")
        assert widths == []

    def test_get_iso_enter_footprints(self, temp_library) -> None:
        discovery = SwitchFootprintDiscovery(str(temp_library))

        iso_footprints = discovery.get_iso_enter_footprints()
        assert "SW_ISO_Enter" in iso_footprints

    def test_find_exact_width(self, temp_library) -> None:
        discovery = SwitchFootprintDiscovery(str(temp_library))

        # Exact match
        width = discovery.find_closest_width("SW_Cherry_MX_PCB", 1.5)
        assert width == 1.5

    def test_find_fallback_to_1u(self, temp_library) -> None:
        discovery = SwitchFootprintDiscovery(str(temp_library))

        # Requested width not available, should fallback to 1.0u
        width = discovery.find_closest_width("SW_Cherry_MX_PCB", 3.0)
        assert width == 1.0

        width = discovery.find_closest_width("SW_Cherry_MX_PCB", 1.25)
        assert width == 1.0

    def test_find_closest_width_when_1u_unavailable(self, tmpdir) -> None:
        # Create library without 1.0u variant
        lib_path = Path(tmpdir) / "test.pretty"
        lib_path.mkdir()

        footprints = [
            "SW_Special_1.50u.kicad_mod",
            "SW_Special_2.00u.kicad_mod",
        ]

        for fp in footprints:
            (lib_path / fp).touch()

        discovery = SwitchFootprintDiscovery(str(lib_path))

        # Should use closest since 1.0u is not available
        # 1.75u is equidistant from 1.5u and 2.0u, so it returns first match (1.5u)
        width = discovery.find_closest_width("SW_Special", 1.75)
        assert width == 1.5

        width = discovery.find_closest_width("SW_Special", 1.0)
        assert width == 1.5

        # 2.5u should be closer to 2.0u
        width = discovery.find_closest_width("SW_Special", 2.5)
        assert width == 2.0

    def test_find_closest_width_no_widths(self) -> None:
        discovery = SwitchFootprintDiscovery("/nonexistent")

        width = discovery.find_closest_width("NonExistent", 1.0)
        assert width is None

    def test_library_not_found(self, tmpdir, caplog) -> None:
        nonexistent = str(Path(tmpdir) / "nonexistent.pretty")
        discovery = SwitchFootprintDiscovery(nonexistent)

        # Should not crash, just log warning
        widths = discovery.get_available_widths("SW_Cherry_MX_PCB")
        assert widths == []
        assert "Library directory not found" in caplog.text

    def test_scan_only_once(self, temp_library) -> None:
        discovery = SwitchFootprintDiscovery(str(temp_library))

        # Multiple calls should only scan once
        discovery.get_available_widths("SW_Cherry_MX_PCB")
        discovery.get_available_widths("SW_Kailh")
        discovery.get_iso_enter_footprints()

        assert discovery._scanned


class TestSwitchFootprintLoader:
    """Tests for SwitchFootprintLoader class."""

    @pytest.fixture
    def examples_library(self) -> Path:
        """Get path to examples library with variable width footprints."""
        test_dir = Path(__file__).parent
        examples_lib = test_dir.parent / "examples" / "examples.pretty"
        if not examples_lib.exists():
            pytest.skip("Examples library not found")
        return examples_lib

    def test_initialization_with_valid_identifier(self) -> None:
        loader = SwitchFootprintLoader("/lib.pretty:SW_Cherry_MX_PCB_1.00u")
        assert loader.identifier.library_path == "/lib.pretty"
        assert loader.identifier.footprint_name == "SW_Cherry_MX_PCB_1.00u"

    def test_initialization_with_invalid_identifier(self) -> None:
        with pytest.raises(ValueError):
            SwitchFootprintLoader("invalid")

    def test_get_footprint_name_simple(self) -> None:
        loader = SwitchFootprintLoader("/lib.pretty:SW_Cherry_MX_PCB_1.00u")
        name = loader.get_footprint_name()
        assert name == "SW_Cherry_MX_PCB_1.00u"

    def test_get_footprint_name_template_with_exact_width(
        self, examples_library
    ) -> None:
        loader = SwitchFootprintLoader(f"{examples_library}:SW_Cherry_MX_PCB_{{:.2f}}u")

        # 1.0u exists
        name = loader.get_footprint_name(key=Key(width=1.0))
        assert name == "SW_Cherry_MX_PCB_1.00u"

        # 1.5u exists
        name = loader.get_footprint_name(key=Key(width=1.5))
        assert name == "SW_Cherry_MX_PCB_1.50u"

    def test_get_footprint_name_template_with_fallback(self, examples_library) -> None:
        loader = SwitchFootprintLoader(f"{examples_library}:SW_Cherry_MX_PCB_{{:.2f}}u")

        # 1.25u doesn't exist, should fallback to 1.0u
        name = loader.get_footprint_name(key=Key(width=1.25))
        assert name == "SW_Cherry_MX_PCB_1.00u"

    def test_get_footprint_name_iso_enter(self, tmpdir) -> None:
        # Create library with ISO Enter footprint
        lib_path = Path(tmpdir) / "test.pretty"
        lib_path.mkdir()
        (lib_path / "SW_ISO_Enter.kicad_mod").touch()
        (lib_path / "SW_Cherry_MX_PCB_1.00u.kicad_mod").touch()

        loader = SwitchFootprintLoader(f"{lib_path}:SW_Cherry_MX_PCB_{{:.2f}}u")

        # ISO Enter key should use ISO Enter footprint
        key = Key(width=1.25, height=2, width2=1.5, height2=1)
        name = loader.get_footprint_name(key=key)
        assert name == "SW_ISO_Enter"

    def test_get_footprint_name_iso_enter_not_available(self, examples_library) -> None:
        # Examples library doesn't have ISO Enter footprint
        loader = SwitchFootprintLoader(f"{examples_library}:SW_Cherry_MX_PCB_{{:.2f}}u")

        # Should fallback to regular footprint
        key = Key(width=1.25, height=2, width2=1.5, height2=1)
        name = loader.get_footprint_name(key=key)
        assert name == "SW_Cherry_MX_PCB_1.00u"  # Fallback to 1.0u

    def test_extract_base_name_from_template(self) -> None:
        loader = SwitchFootprintLoader("/lib.pretty:SW_Cherry_MX_PCB_{:.2f}u")
        base_name = loader._extract_base_name_from_template()
        assert base_name == "SW_Cherry_MX_PCB"

        loader = SwitchFootprintLoader("/lib.pretty:switch_{}u")
        base_name = loader._extract_base_name_from_template()
        assert base_name == "switch"

    def test_load_simple_footprint(self) -> None:
        # This test requires actual KiCad installation
        test_dir = Path(__file__).parent
        test_lib = test_dir / "data" / "footprints" / "tests.pretty"

        if not test_lib.exists():
            pytest.skip("Test library not found")

        loader = SwitchFootprintLoader(f"{test_lib}:SW_Cherry_MX_PCB_1.00u")
        fp = loader.load()

        assert fp is not None
        assert fp.GetFPID().GetUniStringLibItemName() == "SW_Cherry_MX_PCB_1.00u"

    def test_load_template_footprint(self, examples_library) -> None:
        loader = SwitchFootprintLoader(f"{examples_library}:SW_Cherry_MX_PCB_{{:.2f}}u")

        # Load 1.5u footprint
        fp = loader.load(key=Key(width=1.5))
        assert fp is not None
        assert fp.GetFPID().GetUniStringLibItemName() == "SW_Cherry_MX_PCB_1.50u"

    def test_load_invalid_footprint(self, tmpdir) -> None:
        lib_path = Path(tmpdir) / "test.pretty"
        lib_path.mkdir()

        loader = SwitchFootprintLoader(f"{lib_path}:NonExistent")

        # pcbnew can raise either RuntimeError or AttributeError depending on conditions
        with pytest.raises((RuntimeError, AttributeError)):
            loader.load()

    def test_lazy_discovery_creation(self) -> None:
        loader = SwitchFootprintLoader("/lib.pretty:SW_Cherry_MX_PCB_1.00u")

        # Discovery should not be created yet
        assert loader._discovery is None

        # Non-template footprint shouldn't create discovery
        name = loader.get_footprint_name()
        assert loader._discovery is None

    def test_lazy_discovery_for_templates(self, tmpdir) -> None:
        lib_path = Path(tmpdir) / "test.pretty"
        lib_path.mkdir()

        loader = SwitchFootprintLoader(f"{lib_path}:SW_Cherry_MX_PCB_{{:.2f}}u")

        # Discovery should be created when needed for template
        name = loader.get_footprint_name(key=Key(width=1.0))
        assert loader._discovery is not None
