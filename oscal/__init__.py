from loguru import logger

# # Disable library logging by default - callers can enable with:
# #   from loguru import logger
# #   logger.enable("oscal")
logger.disable("oscal")

from . import oscal_support_class as oscal_support  # noqa: E402
from . import oscal_content_class # noqa: E402
from . import oscal_datatypes # noqa: E402
from . import oscal_markdown # noqa: E402
from . import oscal_controls # noqa: E402
from . import oscal_assessment # noqa: E402
from . import oscal_implementation # noqa: E402

# Import commonly used constants
from .oscal_support_class import OSCAL_FORMATS, OSCAL_DEFAULT_XML_NAMESPACE # noqa: E402

# Import model-specific classes for convenient access
from .oscal_controls import Catalog, Profile, Mapping  # noqa: E402
from .oscal_implementation import ComponentDefinition, SSP  # noqa: E402
from .oscal_assessment import AssessmentPlan, AssessmentResults, POAM  # noqa: E402

# Import factory dependencies
from .oscal_content_class import OSCAL, get_shared_oscal_support  # noqa: E402
from .oscal_support_class import SUPPORT_DATABASE_DEFAULT_TYPE  # noqa: E402
from .oscal_datatypes import oscal_date_time_with_timezone  # noqa: E402
from ruf_common.data import detect_data_format, safe_load, safe_load_xml  # noqa: E402
from ruf_common.lfs import getfile  # noqa: E402
from typing import Optional  # noqa: E402

# Map OSCAL model names to their subclasses
_MODEL_CLASS_MAP = {
    "catalog": Catalog,
    "profile": Profile,
    "mapping": Mapping,
    "component-definition": ComponentDefinition,
    "system-security-plan": SSP,
    "assessment-plan": AssessmentPlan,
    "assessment-results": AssessmentResults,
    "plan-of-action-and-milestones": POAM,
}

def _detect_oscal_model(content: str) -> str:
    """
    Lightweight detection of the OSCAL model name from content.
    Parses just enough to identify the root element without full OSCAL initialization.

    Args:
        content (str): Raw OSCAL content string (XML, JSON, or YAML).

    Returns:
        str: The OSCAL model name (e.g., "catalog", "system-security-plan"), or "" if undetectable.
    """
    fmt = detect_data_format(content)
    if fmt == "xml":
        tree = safe_load_xml(content)
        if tree is not None:
            from xml.etree import ElementTree
            import elementpath
            nsmap = {"": OSCAL_DEFAULT_XML_NAMESPACE}
            results = elementpath.select(tree, "/*/name()", namespaces=nsmap)
            if results:
                return str(results[0])
    elif fmt in ("json", "yaml"):
        loaded = safe_load(content, fmt)
        if isinstance(loaded, dict) and loaded:
            return next(iter(loaded.keys()))
    return ""


def load(content: str = "", filename: str = "", url: str = "", support_db_conn: str = "", support_db_type: str = SUPPORT_DATABASE_DEFAULT_TYPE) -> Optional[OSCAL]:
    """
    Load existing OSCAL content and return the appropriate model-specific subclass.
    Accepts content as a string, a local filename, or a URL.

    Args:
        content (str): A string containing OSCAL content (XML, JSON, or YAML).
        filename (str): Path to a local file containing OSCAL content.
        url (str): URL to fetch OSCAL content from.
        support_db_conn (str): Optional database connection for OSCAL Support instance.
        support_db_type (str): Database type (default: "sqlite3").

    Returns:
        Optional[OSCAL]: The appropriate OSCAL subclass instance, or None on failure.

    Raises:
        ValueError: If none of content, filename, or url is provided.
    """
    if not content and not filename and not url:
        raise ValueError("Must provide at least one of: content, filename, or url.")

    # Resolve content from filename or URL if not provided directly
    source_filename = filename
    if not content and url:
        logger.debug(f"Fetching OSCAL content from URL: {url}")
        from ruf_common import network
        content = network.geturl(url)
        if not content:
            logger.error(f"Unable to fetch content from URL: {url}")
            return None

    if not content and filename:
        logger.debug(f"Loading OSCAL content from file: {filename}")
        content = getfile(filename)
        if not content:
            logger.error(f"Unable to load file: {filename}")
            return None

    # Detect the model name from content
    model_name = _detect_oscal_model(content)
    if not model_name:
        logger.error("Unable to detect OSCAL model from content.")
        return None

    target_class = _MODEL_CLASS_MAP.get(model_name, OSCAL)
    logger.debug(f"Detected OSCAL model '{model_name}', using class {target_class.__name__}")

    try:
        oscal_object = target_class(
            content=content,
            filename=source_filename,
            support_db_conn=support_db_conn,
            support_db_type=support_db_type,
        )
        return oscal_object
    except ValueError as ve:
        logger.error(f"ValueError loading OSCAL content: {str(ve)}")
        return None
    except Exception as error:
        logger.error(f"Error loading OSCAL content: {type(error).__name__} - {str(error)}")
        return None


__all__ = [
    "oscal_support",
    "oscal_content_class",
    "oscal_datatypes",
    "oscal_markdown",
    "oscal_controls",
    "oscal_implementation",
    "CatalogBase",
    "Catalog",
    "Controls",
    "Profile",
    "ComponentDefinition",
    "SSP",
    "AssessmentPlan",
    "AssessmentResults",
    "POAM",
    "OSCAL",
    "OSCAL_FORMATS",
    "OSCAL_DEFAULT_XML_NAMESPACE",
    "new",
    "load",
    "create_new_oscal_content"
]
