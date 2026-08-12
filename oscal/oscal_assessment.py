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
# DEVELOPER NOTE — assessment tasks not yet implemented (parking lot)
# ---------------------------------------------------------------------------
# These assessment classes are currently stubs (register + inherit base OSCAL).
# Task accessors are NOT implemented yet.
#
# When tasks ARE implemented, mirror the catalog/profile control-getter pattern
# for payload/ownership (see oscal_controls.get_control_by_id / get_group_by_id):
#   * Add a `depth: int | None = None` parameter to task getters. Tasks can nest
#     (a task may contain child `tasks`), so `depth` prunes ONLY the nested
#     `tasks` collection — i.e. child_keys=("tasks",). The task node's own
#     intrinsic content (props, links, activities, etc.) is always returned in
#     full. `depth=None` = unlimited (mimics returning the whole subtree).
#   * All getters return SAFE COPIES — never live references. Mutation must go
#     through the enforcing (OSCAL-standard-aware) methods; the only live whole-
#     document access remains the private `_dict` attribute.
# The task nesting here is lighter than catalog control nesting, but the same
# depth/ownership contract should apply for consistency across models.
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
