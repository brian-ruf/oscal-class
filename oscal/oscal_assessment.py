"""
Functions specific to OSCAL assessment objects. (AP, AR, and POA&M)
"""
from .oscal_content_class import OSCAL

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class AssessmentPlan(OSCAL):
    """Class representing an OSCAL Assessment Plan (AP) object."""
    def _init_common(self):
        super()._init_common()        # run OSCAL's common init first

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class AssessmentResults(OSCAL):
    """Class representing an OSCAL Assessment Results (AR) object."""
    def _init_common(self):
        super()._init_common()        # run OSCAL's common init first

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class POAM(OSCAL):
    """Class representing an OSCAL Plan of Action and Milestones (POA&M) object."""
    def _init_common(self):
        super()._init_common()        # run OSCAL's common init first
