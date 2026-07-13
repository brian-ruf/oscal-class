"""
oscal_assessment — OSCAL assessment-layer model classes.

Provides the model classes for the OSCAL assessment models: ``AssessmentPlan``
(Security Assessment Plan / SAP), ``AssessmentResults`` (Security Assessment
Results / SAR), and ``POAM`` (Plan of Action and Milestones). Each subclasses
``OSCAL`` from ``oscal_content`` and inherits its common load/save/validate and
query behavior.

Module constants:
    (none exported)
"""
from .oscal_content import OSCAL, register_model

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class AssessmentPlan(OSCAL):
    """OSCAL Assessment Plan (AP / SAP) model.

    Represents an assessment plan that defines the scope, assets, activities,
    and tasks for a security assessment. Subclasses ``OSCAL``.
    """
    def _init_common(self):
        super()._init_common()        # run OSCAL's common init first

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class AssessmentResults(OSCAL):
    """OSCAL Assessment Results (AR / SAR) model.

    Represents the findings, observations, and risks produced by executing an
    assessment plan. Subclasses ``OSCAL``.
    """
    def _init_common(self):
        super()._init_common()        # run OSCAL's common init first

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class POAM(OSCAL):
    """OSCAL Plan of Action and Milestones (POA&M) model.

    Represents tracked security findings and their planned remediation
    milestones. Subclasses ``OSCAL``.
    """
    def _init_common(self):
        super()._init_common()        # run OSCAL's common init first

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Register model classes so OSCAL factory methods return typed instances.
register_model("assessment-plan", AssessmentPlan)
register_model("assessment-results", AssessmentResults)
register_model("plan-of-action-and-milestones", POAM)
