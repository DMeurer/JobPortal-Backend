#!/usr/bin/env python
"""
Setup script for Job Portal Backend

This script helps initialize the database and create the first migration.
"""

import os
import sys
import subprocess


def run_command(command, description):
    """Run a shell command and handle errors."""
    print(f"\n{'='*70}")
    print(f"{description}")
    print(f"{'='*70}")
    print(f"Running: {command}")

    result = subprocess.run(command, shell=True, capture_output=True, text=True)

    if result.stdout:
        print(result.stdout)

    if result.returncode != 0:
        print(f"Error: Command failed with exit code {result.returncode}")
        if result.stderr:
            print(result.stderr)
        return False

    return True


def create_initial_admin_key():
    """Create the initial admin API key after migrations are complete."""
    print("\n" + "=" * 70)
    print("Creating Initial Admin API Key")
    print("=" * 70)

    try:
        # Import after migrations are complete
        from app.database import SessionLocal
        from app.models import APIKey
        from app import services, schemas

        db = SessionLocal()

        # Check if any admin keys exist
        existing_admin = db.query(APIKey).filter(APIKey.admin == True).first()

        if existing_admin:
            print("Admin API key already exists. Skipping creation.")
            db.close()
            return True

        # Create initial admin key
        admin_key_data = schemas.APIKeyCreate(
            name="Initial Admin Key",
            description="Created during setup - full admin access",
            admin=True,
            read=True,
            write=True
        )

        admin_key = services.APIKeyService.create_api_key(db, admin_key_data)

        print("\n" + "!" * 70)
        print("IMPORTANT: Save this API key securely!")
        print("!" * 70)
        print(f"\nAPI Key: {admin_key.key}")
        print(f"Name: {admin_key.name}")
        print(f"Permissions: admin, read, write")
        print("\nThis key will NOT be shown again!")
        print("!" * 70)

        # Optionally save to a file
        with open(".initial_admin_key.txt", "w") as f:
            f.write(f"Initial Admin API Key\n")
            f.write(f"{'=' * 50}\n")
            f.write(f"Key: {admin_key.key}\n")
            f.write(f"Created: {admin_key.created_at}\n")
            f.write(f"Permissions: admin, read, write\n")
            f.write(f"\nIMPORTANT: Delete this file after saving the key securely!\n")

        print(f"\nKey also saved to: .initial_admin_key.txt")
        print("IMPORTANT: Delete this file after saving the key securely!")

        db.close()
        return True

    except Exception as e:
        print(f"Error creating admin key: {str(e)}")
        return False


def main():
    print("Job Portal Backend Setup")
    print("=" * 70)

    # Check if .env exists
    if not os.path.exists(".env"):
        print("\nWarning: .env file not found!")
        print("Please create a .env file based on .env.example")
        print("Example:")
        print("  cp .env.example .env")
        print("  # Then edit .env with your database credentials")
        response = input("\nDo you want to continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("Setup cancelled.")
            return 1

    # Install dependencies
    if not run_command(
        "uv pip install -r pyproject.toml",
        "Installing dependencies"
    ):
        return 1

    # Create initial migration
    if not run_command(
        "alembic revision --autogenerate -m 'Initial migration'",
        "Creating initial migration"
    ):
        print("\nNote: If the migration already exists, you can skip this error.")

    # Run migrations
    if not run_command(
        "alembic upgrade head",
        "Running migrations"
    ):
        return 1

    # Create initial admin API key
    if not create_initial_admin_key():
        print("\nWarning: Failed to create admin API key")
        print("You can create one manually later using the API")

    print("\n" + "=" * 70)
    print("Setup completed successfully!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Save the admin API key shown above")
    print("2. Start the server:")
    print("   uvicorn app.main:app --reload")
    print("\n3. Test the API with your key:")
    print("   curl -H 'X-API-Key: <your-key>' http://localhost:8000/api/companies")
    print("\n4. Visit the API documentation:")
    print("   http://localhost:8000/docs")

    return 0


if __name__ == "__main__":
    sys.exit(main())
