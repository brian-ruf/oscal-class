"""Shared pytest fixtures for the unit test suite."""
import pytest

from oscal.oscal_registry import get_registry


@pytest.fixture(autouse=True)
def _isolate_object_registry():
    """Clear the process-wide OSCAL object registry around every test.

    The registry is a session-level identity map keyed by
    ``(uuid, last-modified, published)``. Test fixtures frequently reuse the same
    placeholder UUIDs, so without isolation a live object from one test can be matched
    by another — silently reused, or (with root-UUID-collision detection) flagged and
    UUID-reassigned — which makes results depend on test order and garbage-collection
    timing. Clearing the registry before and after each test keeps them independent.
    """
    get_registry().clear()
    yield
    get_registry().clear()
