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
from .oscal_controls import Catalog, Profile  # noqa: E402
from .oscal_implementation import ComponentDefinition, SSP  # noqa: E402
from .oscal_assessment import AssessmentPlan, AssessmentResults, POAM  # noqa: E402

# Import factory dependencies
from .oscal_content_class import OSCAL, get_shared_oscal_support  # noqa: E402
from .oscal_support_class import SUPPORT_DATABASE_DEFAULT_TYPE  # noqa: E402
from .oscal_datatypes import oscal_date_time_with_timezone  # noqa: E402
from typing import Optional  # noqa: E402

# Map OSCAL model names to their subclasses
_MODEL_CLASS_MAP = {
    "catalog": Catalog,
    "profile": Profile,
    "component-definition": ComponentDefinition,
    "system-security-plan": SSP,
    "assessment-plan": AssessmentPlan,
    "assessment-results": AssessmentResults,
    "plan-of-action-and-milestones": POAM,
}

def new(model_name: str, title: str, version: str = "", published: str = "", support_db_conn: str = "", support_db_type: str = SUPPORT_DATABASE_DEFAULT_TYPE) -> Optional[OSCAL]:
    """
    Factory function that returns minimally valid OSCAL content as the
    appropriate model-specific subclass (e.g., Catalog, Profile, SSP).
    Currently this is based on loading a template file from package data.
    In the future, this should be generated based on the latest metaschema definition.

    Args:
        model_name (str): The OSCAL model name (e.g., "catalog", "system-security-plan").
        title (str): The title for the new OSCAL content.
        version (str): Optional content version.
        published (str): Optional publication date.
        support_db_conn (str): Optional database connection for OSCAL Support instance.
        support_db_type (str): Database type (default: "sqlite3").

    Returns:
        Optional[OSCAL]: The appropriate OSCAL subclass instance, or None on failure.
    """
    oscal_object = None
    support = get_shared_oscal_support(db_conn=support_db_conn, db_type=support_db_type)

    if support.is_model_valid(model_name):
        content = support.load_file(f"{model_name}.xml", binary=False)
        if content and isinstance(content, str):
            try:
                target_class = _MODEL_CLASS_MAP.get(model_name, OSCAL)
                oscal_object = target_class(content=content)
                logger.debug(f"Created new {target_class.__name__} for model {model_name}")

                if oscal_object is not None:
                    metadata = {}
                    if title != "":
                        metadata["title"] = title
                    if version != "":
                        metadata["version"] = version
                    if published != "":
                        metadata["published"] = oscal_date_time_with_timezone(published)

                    if metadata:
                        oscal_object.set_metadata(metadata)

                    oscal_object.content_modified()
            except ValueError as ve:
                logger.error(f"ValueError creating new OSCAL content for model {model_name}: {str(ve)}")
                oscal_object = None
            except Exception as error:
                logger.error(f"Error creating new OSCAL content for model {model_name}: {type(error).__name__} - {str(error)}")
                oscal_object = None
    else:
        logger.error(f"Unsupported OSCAL model for new content: {model_name}")

    return oscal_object

# Backward-compatible alias
create_new_oscal_content = new

__all__ = [
    "oscal_support",
    "oscal_content_class",
    "oscal_datatypes",
    "oscal_markdown",
    "oscal_controls",
    "oscal_implementation",
    "Catalog",
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
    "create_new_oscal_content"
]
