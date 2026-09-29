"""
OSCAL (Open Security Controls Assessment Language) library for Python.
Provides classes and functions for working with OSCAL content, including
loading, saving, and manipulating OSCAL control, implementation 
and assessment content.

"""
import logging
from importlib.metadata import version as _pkg_version, PackageNotFoundError

# Package version, read from the installed distribution metadata (baked in from
# pyproject.toml's [project] version at build time). pyproject.toml is a build
# input, not a runtime artifact, so we never parse it directly — importlib.metadata
# is the single, install-agnostic source. Falls back when running from a source
# tree that was never installed (e.g. no egg-info/dist-info present).
try:
    __version__ = _pkg_version("oscal")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0.0.0+unknown"

# The library emits log records but installs no handler of its own, so it stays
# silent unless the calling application configures logging. Consumers enable it
# with e.g. ``logging.getLogger("oscal").setLevel(logging.INFO)`` plus a handler
# of their choosing. See docs/LOGGING.md.
logging.getLogger("oscal").addHandler(logging.NullHandler())

from . import oscal_support  # noqa: E402
from . import oscal_helpers # noqa: E402
from . import oscal_source # noqa: E402
from . import oscal_content # noqa: E402
from . import oscal_datatypes # noqa: E402
from . import oscal_controls # noqa: E402
from . import oscal_assessment # noqa: E402
from . import oscal_implementation # noqa: E402
from . import oscal_registry # noqa: E402
from . import oscal_cache # noqa: E402
from . import oscal_workspace # noqa: E402
from . import metaschema_parser # noqa: E402

# Import commonly used constants
from .oscal_support import OSCAL_FORMATS, OSCAL_DEFAULT_XML_NAMESPACE # noqa: E402

# Remote-content cache control
from .oscal_cache import CacheDirective, CACHE_FOREVER, CACHE_NEVER, LOCAL_CACHE_TTL # noqa: E402

# Import model-specific classes for convenient access
from .oscal_controls import Catalog, Profile, Mapping  # noqa: E402
from .oscal_implementation import ComponentDefinition, SSP  # noqa: E402
from .oscal_assessment import AssessmentPlan, AssessmentResults, POAM  # noqa: E402

# Import factory dependencies
from .oscal_content import OSCAL  # noqa: E402
from .oscal_datatypes import oscal_date_time_with_timezone  # noqa: E402
from .oscal_workspace import Workspace  # noqa: E402

# Library exception hierarchy
from .oscal_content import OSCALError, UnsupportedModelOperation  # noqa: E402
__all__ = [
    "__version__",
    "oscal_support",
    "oscal_helpers",
    "oscal_source",
    "oscal_content",
    "oscal_datatypes",
    "oscal_controls",
    "oscal_implementation",
    "oscal_assessment",
    "oscal_registry",
    "oscal_cache",
    "oscal_workspace",
    "metaschema_parser",
    "Catalog",
    "Profile",
    "Mapping",
    "ComponentDefinition",
    "SSP",
    "AssessmentPlan",
    "AssessmentResults",
    "POAM",
    "OSCAL",
    "OSCALError",
    "UnsupportedModelOperation",
    "Workspace",
    "oscal_date_time_with_timezone",
    "OSCAL_FORMATS",
    "OSCAL_DEFAULT_XML_NAMESPACE",
    "CacheDirective",
    "CACHE_FOREVER",
    "CACHE_NEVER",
    "LOCAL_CACHE_TTL",
]
