"""
API Client for Job Portal Backend

This module provides a simple client for interacting with the Job Portal API.
Scrapers can use this client instead of directly connecting to the database.
"""

import requests
from datetime import date
from typing import Dict, List, Optional


class JobPortalClient:
    """Client for interacting with the Job Portal API."""

    def __init__(self, base_url: str = "http://localhost:8000", api_key: Optional[str] = None):
        """
        Initialize the API client.

        Args:
            base_url: Base URL of the API (default: http://localhost:8000)
            api_key: API key for authentication (required for protected endpoints)
        """
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

        if api_key:
            self.session.headers.update({"X-API-Key": api_key})

    def insert_job(
        self,
        company_name: str,
        job_data: Dict,
        scrape_date: Optional[date] = None
    ) -> Dict:
        """
        Insert or update a job via the API.

        Args:
            company_name: Name of the company
            job_data: Dictionary containing job information
            scrape_date: Date of the scrape (defaults to today)

        Returns:
            Response dictionary with job_id, insert_id, is_new_job, and message

        Example:
            client = JobPortalClient()
            result = client.insert_job(
                company_name="BBraun",
                job_data={
                    "JobID": "12345",
                    "Title": "Software Engineer",
                    "URL": "https://example.com/job/12345",
                    "WorkLocation": "Germany"
                }
            )
        """
        url = f"{self.base_url}/api/jobs"

        payload = {
            "company_name": company_name,
            "job_id": job_data.get("JobID") or job_data.get("job_id"),
            "url": job_data.get("URL") or job_data.get("url"),
            "url_title": job_data.get("UrlTitle") or job_data.get("url_title"),
            "title": job_data.get("Title") or job_data.get("title"),
            "function": job_data.get("Function") or job_data.get("function"),
            "level": job_data.get("Level") or job_data.get("level"),
            "contract_type": job_data.get("ContractType") or job_data.get("contract_type"),
            "work_location": job_data.get("WorkLocation") or job_data.get("work_location"),
            "work_location_short": job_data.get("WorkLocationShort") or job_data.get("work_location_short"),
            "work_location_with_coordinates": job_data.get("WorkLocationWithCoordinates") or job_data.get("work_location_with_coordinates"),
            "all_locations": job_data.get("AllLocations") or job_data.get("all_locations"),
            "coordinates_primary": job_data.get("CoordinatesPrimary") or job_data.get("coordinates_primary"),
            "country": job_data.get("Country") or job_data.get("country"),
            "currency": job_data.get("Currency") or job_data.get("currency"),
            "supported_locales": job_data.get("SupportedLocales") or job_data.get("supported_locales"),
            "department": job_data.get("Department") or job_data.get("department"),
            "flexibility": job_data.get("Flexibility") or job_data.get("flexibility"),
            "keywords": job_data.get("Keywords") or job_data.get("keywords"),
            "description": job_data.get("Description") or job_data.get("description"),
            "tasks": job_data.get("Tasks") or job_data.get("tasks"),
            "qualifications": job_data.get("Qualifications") or job_data.get("qualifications"),
            "offerings": job_data.get("Offerings") or job_data.get("offerings"),
            "contact_person": job_data.get("ContactPerson") or job_data.get("contact_person"),
            "contact_email": job_data.get("ContactEmail") or job_data.get("contact_email"),
            "contact_phone": job_data.get("ContactPhone") or job_data.get("contact_phone"),
            "unified_url_title": job_data.get("UnifiedUrlTitle") or job_data.get("unified_url_title"),
            "unified_standard_end": job_data.get("UnifiedStandardEnd") or job_data.get("unified_standard_end"),
            "unified_standard_start": job_data.get("UnifiedStandardStart") or job_data.get("unified_standard_start"),
            "scrape_date": scrape_date.isoformat() if scrape_date else date.today().isoformat()
        }

        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}

        response = self.session.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def get_companies(self) -> List[Dict]:
        """
        Get all companies from the API.

        Returns:
            List of company dictionaries

        Example:
            client = JobPortalClient()
            companies = client.get_companies()
            for company in companies:
                print(f"{company['id']}: {company['name']}")
        """
        url = f"{self.base_url}/api/companies"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def create_company(self, name: str) -> Dict:
        """
        Create a new company via the API.

        Args:
            name: Name of the company

        Returns:
            Created company dictionary

        Example:
            client = JobPortalClient()
            company = client.create_company("NewCompany")
        """
        url = f"{self.base_url}/api/companies"
        payload = {"name": name}
        response = self.session.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def close(self):
        """Close the session."""
        self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# Example usage
if __name__ == "__main__":
    with JobPortalClient() as client:
        # Get all companies
        print("Fetching companies...")
        companies = client.get_companies()
        print(f"Found {len(companies)} companies")
        for company in companies:
            print(f"  - {company['name']}")

        # Insert a test job
        print("\nInserting test job...")
        result = client.insert_job(
            company_name="BBraun",
            job_data={
                "JobID": "test-123",
                "Title": "Test Engineer",
                "URL": "https://example.com/test-123",
                "WorkLocation": "Germany"
            }
        )
        print(f"Result: {result['message']}")
        print(f"Job ID: {result['job_id']}, Insert ID: {result['insert_id']}")
