from fastapi import Header, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.services import APIKeyService
from app import models


class AuthError(HTTPException):
    """Custom exception for authentication errors."""
    def __init__(self, detail: str):
        super().__init__(status_code=401, detail=detail)


class PermissionError(HTTPException):
    """Custom exception for permission errors."""
    def __init__(self, detail: str):
        super().__init__(status_code=403, detail=detail)


def get_api_key_header(
    request: Request,
    x_api_key: Optional[str] = Header(None)
) -> Optional[str]:
    """
    Extract API key from X-API-Key header.
    Allow OPTIONS requests (CORS preflight) to pass through without authentication.

    Args:
        request: FastAPI request object
        x_api_key: API key from header

    Returns:
        API key string or None for OPTIONS requests

    Raises:
        AuthError: If header is missing (except for OPTIONS requests)
    """
    # Allow OPTIONS requests for CORS preflight
    if request.method == "OPTIONS":
        return None

    if not x_api_key:
        raise AuthError("X-API-Key header is required")
    return x_api_key


def get_current_api_key(
    api_key: Optional[str] = Depends(get_api_key_header),
    db: Session = Depends(get_db)
) -> Optional[models.APIKey]:
    """
    Validate API key and return the APIKey model.
    Returns None for OPTIONS requests (CORS preflight).

    Args:
        api_key: API key string from header (None for OPTIONS)
        db: Database session

    Returns:
        APIKey model instance or None for OPTIONS requests

    Raises:
        AuthError: If API key is invalid or inactive
    """
    # Allow OPTIONS requests for CORS preflight
    if api_key is None:
        return None

    db_api_key = APIKeyService.get_api_key_by_key(db, api_key)

    if not db_api_key:
        raise AuthError("Invalid or inactive API key")

    # Update last used timestamp
    APIKeyService.update_last_used(db, db_api_key)

    return db_api_key


def require_read_permission(
    api_key: Optional[models.APIKey] = Depends(get_current_api_key)
) -> Optional[models.APIKey]:
    """
    Require read permission.
    Allow OPTIONS requests (CORS preflight) to pass through.

    Args:
        api_key: Current API key (None for OPTIONS)

    Returns:
        APIKey model instance or None for OPTIONS requests

    Raises:
        PermissionError: If key lacks read permission
    """
    # Allow OPTIONS requests for CORS preflight
    if api_key is None:
        return None

    if not APIKeyService.verify_permission(api_key, "read"):
        raise PermissionError("This operation requires 'read' permission")
    return api_key


def require_write_permission(
    api_key: Optional[models.APIKey] = Depends(get_current_api_key)
) -> Optional[models.APIKey]:
    """
    Require write permission.
    Allow OPTIONS requests (CORS preflight) to pass through.

    Args:
        api_key: Current API key (None for OPTIONS)

    Returns:
        APIKey model instance or None for OPTIONS requests

    Raises:
        PermissionError: If key lacks write permission
    """
    # Allow OPTIONS requests for CORS preflight
    if api_key is None:
        return None

    if not APIKeyService.verify_permission(api_key, "write"):
        raise PermissionError("This operation requires 'write' permission")
    return api_key


def require_admin_permission(
    api_key: Optional[models.APIKey] = Depends(get_current_api_key)
) -> Optional[models.APIKey]:
    """
    Require admin permission.
    Allow OPTIONS requests (CORS preflight) to pass through.

    Args:
        api_key: Current API key (None for OPTIONS)

    Returns:
        APIKey model instance or None for OPTIONS requests

    Raises:
        PermissionError: If key lacks admin permission
    """
    # Allow OPTIONS requests for CORS preflight
    if api_key is None:
        return None

    if not APIKeyService.verify_permission(api_key, "admin"):
        raise PermissionError("This operation requires 'admin' permission")
    return api_key
