"""
Input sanitization utilities for database queries.

This module provides functions to sanitize user inputs before they are used
in database queries to prevent injection attacks and other security issues.
"""

import re
from typing import Optional


def sanitize_like_pattern(value: Optional[str]) -> Optional[str]:
    """
    Sanitize a string for use in SQL LIKE patterns.

    Escapes special LIKE pattern characters (% and _) so they are treated
    as literal characters rather than wildcards.

    Args:
        value: The input string to sanitize

    Returns:
        Sanitized string with escaped LIKE wildcards, or None if input is None
    """
    if value is None:
        return None

    # Escape backslashes first, then LIKE wildcards
    value = value.replace('\\', '\\\\')
    value = value.replace('%', '\\%')
    value = value.replace('_', '\\_')

    return value


def sanitize_regex(value: Optional[str], max_length: int = 500) -> Optional[str]:
    """
    Sanitize and validate a regex pattern to prevent ReDoS attacks.

    Checks for potentially dangerous regex patterns that could cause
    catastrophic backtracking and enforces length limits.

    Args:
        value: The regex pattern to sanitize
        max_length: Maximum allowed length for the pattern (default: 500)

    Returns:
        The validated regex pattern, or None if input is None

    Raises:
        ValueError: If the regex pattern is invalid or potentially dangerous
    """
    if value is None:
        return None

    # Enforce length limit
    if len(value) > max_length:
        raise ValueError(f"Regex pattern exceeds maximum length of {max_length} characters")

    # Check for potentially dangerous patterns that could cause ReDoS
    # These patterns can cause catastrophic backtracking
    dangerous_patterns = [
        r'\(\.\*\)\+',           # (.*)+
        r'\(\.\+\)\+',           # (.+)+
        r'\(\[.*\]\*\)\+',       # ([...]*)+
        r'\(\[.*\]\+\)\+',       # ([...]+)+
        r'\(\.\*\)\*',           # (.*)*
        r'\(\.\+\)\*',           # (.+)*
        r'\(.*\+.*\)\{.*,.*\}',  # Nested quantifiers with bounds
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, value):
            raise ValueError("Regex pattern contains potentially dangerous constructs")

    # Count nested groups - too many can cause issues
    open_parens = value.count('(') - value.count('\\(')
    if open_parens > 10:
        raise ValueError("Regex pattern contains too many nested groups")

    # Validate that the regex compiles
    try:
        re.compile(value)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {e}")

    return value


def sanitize_string(value: Optional[str], max_length: int = 1000) -> Optional[str]:
    """
    General string sanitization for database inputs.

    Strips whitespace, enforces length limits, and removes null bytes.

    Args:
        value: The input string to sanitize
        max_length: Maximum allowed length (default: 1000)

    Returns:
        Sanitized string, or None if input is None
    """
    if value is None:
        return None

    # Remove null bytes which can cause issues
    value = value.replace('\x00', '')

    # Strip leading/trailing whitespace
    value = value.strip()

    # Enforce length limit
    if len(value) > max_length:
        value = value[:max_length]

    return value
