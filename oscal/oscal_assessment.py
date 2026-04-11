"""
Functions specific to OSCAL assessment objects. (AP, AR, and POA&M)
"""
from .oscal_content_class import OSCAL

class AssessmentPlan(OSCAL):
    """Class representing an OSCAL Assessment Plan (AP) object."""
    pass

class AssessmentResults(OSCAL):
    """Class representing an OSCAL Assessment Results (AR) object."""
    pass

class POAM(OSCAL):
    """Class representing an OSCAL Plan of Action and Milestones (POA&M) object."""
    pass
