"""
Functions specific to OSCAL assessment objects. (AP, AR, and POA&M)
"""
from .oscal_content_class import OSCAL

class assessment_plan(OSCAL):
    """Class representing an OSCAL Assessment Plan (AP) object."""
    pass

class assessment_results(OSCAL):
    """Class representing an OSCAL Assessment Results (AR) object."""
    pass

class poam(OSCAL):
    """Class representing an OSCAL Plan of Action and Milestones (POA&M) object."""
    pass
