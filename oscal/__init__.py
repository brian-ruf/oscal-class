"""
OSCAL (Open Security Controls Assessment Language) library for Python.
Provides classes and functions for working with OSCAL content, including
loading, saving, and manipulating OSCAL control, implementation 
and assessment content.

"""
from loguru import logger
logger.disable("oscal") # Disable logging for oscal library by default.
# Callers can enable with:
#   from loguru import logger
#   logger.enable("oscal")

from . import oscal_support  # noqa: E402
from . import oscal_content # noqa: E402
from . import oscal_datatypes # noqa: E402
from . import oscal_controls # noqa: E402
from . import oscal_assessment # noqa: E402
from . import oscal_implementation # noqa: E402

# Import commonly used constants
from .oscal_support import OSCAL_FORMATS, OSCAL_DEFAULT_XML_NAMESPACE # noqa: E402

# Import model-specific classes for convenient access
from .oscal_controls import Catalog, Profile, Mapping  # noqa: E402
from .oscal_implementation import ComponentDefinition, SSP  # noqa: E402
from .oscal_assessment import AssessmentPlan, AssessmentResults, POAM  # noqa: E402

# Import factory dependencies
from .oscal_content import OSCAL  # noqa: E402
from .oscal_datatypes import oscal_date_time_with_timezone  # noqa: E402
__all__ = [
    "oscal_support",
    "oscal_content",
    "oscal_datatypes",
    "oscal_controls",
    "oscal_implementation",
    "oscal_assessment",
    "Catalog",
    "Profile",
    "Mapping",
    "ComponentDefinition",
    "SSP",
    "AssessmentPlan",
    "AssessmentResults",
    "POAM",
    "OSCAL",
    "oscal_date_time_with_timezone",
    "OSCAL_FORMATS",
    "OSCAL_DEFAULT_XML_NAMESPACE"
]
