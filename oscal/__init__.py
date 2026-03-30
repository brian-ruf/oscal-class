from loguru import logger

# # Disable library logging by default - callers can enable with:
# #   from loguru import logger
# #   logger.enable("oscal")
logger.disable("oscal")

from . import oscal_support_class as oscal_support  # noqa: E402
from . import oscal_content_class # noqa: E402
from . import oscal_datatypes # noqa: E402
from . import oscal_markdown # noqa: E402
# from . import oscal_controls # noqa: E402
# from . import oscal_assessment # noqa: E402
# from . import oscal_implementation # noqa: E402

# Import commonly used constants
from .oscal_support_class import OSCAL_FORMATS, OSCAL_DEFAULT_XML_NAMESPACE # noqa: E402

__all__ = [
    "oscal_support",
    "oscal_content_class",
    "oscal_datatypes",
    "oscal_markdown",
    # "catalog",
    # "profile",
    # "component_definition",
    # "ssp",
    # "assessment_plan",
    # "assessment_results",
    # "poam",
    "OSCAL_FORMATS",
    "OSCAL_DEFAULT_XML_NAMESPACE"
]
