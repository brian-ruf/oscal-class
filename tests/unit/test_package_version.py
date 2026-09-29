"""
Unit tests for the package version surface (oscal.__version__).

The version is a module-level string attribute (Python convention), sourced from the
installed distribution metadata via importlib.metadata — which is baked in from
pyproject.toml's [project] version at build time. pyproject.toml is never parsed at
runtime.
"""
import re

from importlib.metadata import version as pkg_version

import oscal


class TestPackageVersion:

    def test_version_attribute_exists(self):
        assert hasattr(oscal, "__version__")

    def test_version_is_non_empty_string(self):
        assert isinstance(oscal.__version__, str)
        assert oscal.__version__.strip() != ""

    def test_version_matches_installed_metadata(self):
        # The attribute must reflect the installed distribution's metadata, not a
        # hard-coded duplicate.
        assert oscal.__version__ == pkg_version("oscal")

    def test_version_is_not_the_uninstalled_fallback(self):
        # When the package is installed (as it is under test), the metadata lookup
        # must succeed rather than hit the "not installed" fallback.
        assert oscal.__version__ != "0.0.0+unknown"

    def test_version_looks_like_a_release_identifier(self):
        # Starts with a numeric release segment (PEP 440-ish: N(.N)*), allowing any
        # pre/post/local suffix after it.
        assert re.match(r"^\d+(\.\d+)*", oscal.__version__)

    def test_version_exported_in_all(self):
        assert "__version__" in oscal.__all__
