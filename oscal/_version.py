"""Single authoritative source of the package version.

Edit the version HERE. ``oscal/__init__.py`` imports ``__version__`` from this module
at runtime, and ``pyproject.toml`` derives the published version from it at build time
(``[tool.setuptools.dynamic] version = {attr = "oscal._version.__version__"}``).

Keep this module trivial — just the assignment, no imports from the rest of the package —
so the build backend can read the literal without importing ``oscal`` (and its
dependencies).
"""
__version__ = "4.1.1"
