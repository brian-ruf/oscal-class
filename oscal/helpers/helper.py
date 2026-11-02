"""
General helper utilities used across ``oscal``.

* :func:`convert_datetime_format` / :func:`datetime_string` — date/time formatting
* :func:`iif` — inline ternary
* :func:`normalize_content` — bytes-or-str → str
* :func:`compare_semver` — semantic-version comparison

All helpers here use only the Python standard library.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Union

logger = logging.getLogger(__name__)


# =============================================================================
# DATE/TIME FUNCTIONS
# =============================================================================
def convert_datetime_format(date_input: Union[str, datetime, None] = None,
                            include_time: bool = True,
                            assume_localtime: bool = True,
                            format: str = "%Y-%m-%dT%H:%M:%SZ") -> str:
    """
    Convert a datetime object or ISO 8601 string to a human-readable date string.

    Standard-library only. ``None`` (the default) uses the current time.
    Timezone-naive inputs are treated as local time when
    ``assume_localtime`` is True, otherwise as UTC; the result is rendered in local time.

    Args:
        date_input: A ``datetime``, an ISO 8601 string, or None (→ now).
        include_time: Include the time component in the output.
        assume_localtime: Interpret naive inputs as local time (else UTC).
        format: Retained for call-compatibility; output format is fixed to
            'Month DD, YYYY[ HH:MM:SS AM/PM]'.

    Returns:
        str: The formatted date, or "" on invalid/empty input.
    """
    if date_input is None:
        date_input = datetime.now()

    if isinstance(date_input, str):
        text = date_input.strip()
        if not text:
            return ""
        try:
            # fromisoformat handles offsets; normalize a trailing 'Z' to +00:00.
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            logger.debug(f"Unhandled date format: {date_input}")
            return ""
    elif isinstance(date_input, datetime):
        dt = date_input
    else:
        logger.debug(f"Invalid input type: {type(date_input)}. Expected str or datetime.")
        return ""

    # Stamp a timezone on naive values (UTC branch is explicit; the local branch is
    # left naive so astimezone() below interprets it as local), then render in local time.
    if dt.tzinfo is None and not assume_localtime:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        dt = dt.astimezone()
    except (ValueError, OSError) as error:
        logger.debug(f"Error converting to local timezone: {error}")

    return dt.strftime("%B %d, %Y %I:%M:%S %p") if include_time else dt.strftime("%B %d, %Y")


# -----------------------------------------------------------------------------
def datetime_string(date_time: Union[datetime, None] = None,
                    format: str = "%Y-%m-%d--%H-%M-%S") -> str:
    """
    Convert a date and time to a formatted string (default: now).

    Args:
        date_time: The datetime to format; None (default) uses the current time.
        format: The ``strftime`` format string (default ``"%Y-%m-%d--%H-%M-%S"``).

    Returns:
        str: The formatted string, or "" if formatting fails.
    """
    if date_time is None:
        date_time = datetime.now()
    try:
        return date_time.strftime(format)
    except (Exception, BaseException) as error:
        logger.error(f"{type(error).__name__} error handling date/time formatting: {str(error)}")
        return ""


# =============================================================================
# LOGIC UTILITIES
# =============================================================================
def iif(condition: Any, if_true: Any, if_false: Any) -> Any:
    """Return ``if_true`` when ``condition`` is truthy, otherwise ``if_false``."""
    if condition:
        return if_true
    else:
        return if_false


# =============================================================================
# STRING UTILITIES
# =============================================================================
def normalize_content(content: Union[str, bytes]) -> str:
    """
    Normalize content to ``str``: decode bytes as UTF-8, pass strings through.

    Args:
        content: A string or bytes value.

    Returns:
        str: The content as a string (non-str/bytes values are returned unchanged).
    """
    if isinstance(content, str):
        pass  # already a string
    elif isinstance(content, bytes):
        content = content.decode("utf-8")
    else:
        logger.debug(f"NORMALIZE: Unhandled content encoding: {type(content)}")

    return content


# =============================================================================
# MISCELLANEOUS FUNCTIONS
# =============================================================================
def compare_semver(version1: str, version2: str) -> int:
    """
    Compare two semantic versions.

    Returns:
        int: ``-1`` if ``version1 < version2``, ``0`` if equal, ``1`` if greater.
    """
    from packaging.version import parse as parse_version

    v1 = parse_version(version1)
    v2 = parse_version(version2)
    if v1 < v2:
        return -1
    elif v1 > v2:
        return 1
    else:
        return 0
