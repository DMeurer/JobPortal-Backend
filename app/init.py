"""
Initialization functions for the application.
"""
from sqlalchemy.orm import Session
from app import models
from app.config import get_settings


def init_fixed_api_keys(db: Session) -> None:
    """
    Initialize the 4 fixed API keys from environment variables.
    Creates or updates them to ensure they always exist with correct permissions.

    API Keys:
    1. Admin - All permissions (admin=True grants all)
    2. Webscraper - Read and write permissions, no admin
    3. Fullread - Read and read_hidden permissions, no write
    4. Frontend - Basic read only, no hidden access

    Args:
        db: Database session
    """
    settings = get_settings()

    # Define the 4 fixed API keys with their configurations
    fixed_keys = [
        {
            "key": settings.api_key_admin,
            "name": "Admin API Key",
            "description": "Master admin key with all permissions",
            "admin": True,
            "read": True,
            "write": True,
            "read_hidden": True,
        },
        {
            "key": settings.api_key_webscraper,
            "name": "Webscraper API Key",
            "description": "Key for web scrapers with read and write permissions",
            "admin": False,
            "read": True,
            "write": True,
            "read_hidden": True,  # Scrapers can access all companies
        },
        {
            "key": settings.api_key_fullread,
            "name": "Full Read API Key",
            "description": "Key with full read access including hidden companies",
            "admin": False,
            "read": True,
            "write": False,
            "read_hidden": True,
        },
        {
            "key": settings.api_key_frontend,
            "name": "Frontend API Key",
            "description": "Basic read-only key for frontend without hidden company access",
            "admin": False,
            "read": True,
            "write": False,
            "read_hidden": False,
        },
    ]

    # Create or update each fixed API key
    for key_config in fixed_keys:
        # Check if key already exists
        existing_key = db.query(models.APIKey).filter(
            models.APIKey.key == key_config["key"]
        ).first()

        if existing_key:
            # Update existing key with correct permissions
            existing_key.name = key_config["name"]
            existing_key.description = key_config["description"]
            existing_key.admin = key_config["admin"]
            existing_key.read = key_config["read"]
            existing_key.write = key_config["write"]
            existing_key.read_hidden = key_config["read_hidden"]
            existing_key.is_active = True
            print(f"Updated fixed API key: {key_config['name']}")
        else:
            # Create new key
            new_key = models.APIKey(
                key=key_config["key"],
                name=key_config["name"],
                description=key_config["description"],
                admin=key_config["admin"],
                read=key_config["read"],
                write=key_config["write"],
                read_hidden=key_config["read_hidden"],
                is_active=True,
            )
            db.add(new_key)
            print(f"Created fixed API key: {key_config['name']}")

    db.commit()
    print("Fixed API keys initialization complete")
