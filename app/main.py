from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional, Union
from datetime import date
from contextlib import asynccontextmanager
from app import models, schemas, services
from app.database import engine, get_db
from app.auth import require_admin_permission, require_read_permission, require_write_permission
from app.services import APIKeyService
from app.init import init_fixed_api_keys

models.Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize application on startup."""
    # Startup: Initialize fixed API keys
    db = next(get_db())
    try:
        init_fixed_api_keys(db)
    finally:
        db.close()
    yield
    # Shutdown: Add cleanup code here if needed


app = FastAPI(title="Job Portal API", version="1.0.0", lifespan=lifespan)

# Configure CORS - must be added immediately after app creation
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=0,  # Don't cache preflight to avoid browser caching issues
)


@app.get("/")
def root():
    return {"message": "Job Portal API is running"}

@app.get("/api/companies", response_model=List[schemas.Company])
def get_companies(
    db: Session = Depends(get_db),
    current_key: models.APIKey = Depends(require_read_permission)
):
    """
    Get all companies (requires read permission).
    Hidden companies are filtered unless API key has read_hidden permission.

    Returns:
        List of all accessible companies in the database
    """
    companies = services.JobService.get_all_companies(db, current_key)
    return companies


@app.post("/api/jobs", response_model=schemas.JobInsertResponse)
def insert_job(
    job_data: schemas.JobInsertRequest,
    db: Session = Depends(get_db),
    current_key: models.APIKey = Depends(require_write_permission)
):
    """
    Insert or update a job and create an insert record (requires write permission).

    Args:
        job_data: Job data to insert/update

    Returns:
        JobInsertResponse with job_id, insert_id, and status information
    """
    try:
        result = services.JobService.insert_job(db, job_data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/companies", response_model=schemas.Company)
def create_company(
    company_data: schemas.CompanyCreate,
    db: Session = Depends(get_db),
    current_key: models.APIKey = Depends(require_write_permission)
):
    """
    Create a new company (requires write permission).

    Args:
        company_data: Company data with name

    Returns:
        Created company
    """
    try:
        company = services.JobService.get_or_create_company(db, company_data.name)
        return company
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/keys", response_model=schemas.APIKeyCreateResponse)
def create_api_key(
    key_data: schemas.APIKeyCreate,
    db: Session = Depends(get_db),
    current_key: models.APIKey = Depends(require_admin_permission)
):
    """
    Create a new API key (requires admin permission).

    Args:
        key_data: API key configuration
        current_key: Current authenticated API key (must have admin)

    Returns:
        Created API key with the key value (shown only once!)
    """
    try:
        api_key = APIKeyService.create_api_key(db, key_data)
        return api_key
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/keys", response_model=List[schemas.APIKey])
def list_api_keys(
    db: Session = Depends(get_db),
    current_key: models.APIKey = Depends(require_admin_permission)
):
    """
    List all API keys (requires admin permission).
    Note: Does not include the actual key values.

    Args:
        current_key: Current authenticated API key (must have admin)

    Returns:
        List of API keys without key values
    """
    return APIKeyService.get_all_api_keys(db)


@app.get("/api/jobs")
def get_jobs(
    statistics: bool = Query(False, description="Return statistics instead of job list"),
    company_name: Optional[str] = Query(None, description="Filter by company name (exact match)"),
    company_id: Optional[int] = Query(None, description="Filter by company ID"),
    found_on_date: Optional[date] = Query(None, description="Filter by scrape date (YYYY-MM-DD)"),
    title_contains: Optional[str] = Query(None, description="Filter jobs containing this substring in title"),
    title_excludes: Optional[str] = Query(None, description="Exclude jobs containing this substring in title"),
    level: Optional[str] = Query(None, description="Filter by level (exact match)"),
    contract_type: Optional[str] = Query(None, description="Filter by contract type (exact match)"),
    location: Optional[str] = Query(None, description="Filter by location (substring search)"),
    function: Optional[str] = Query(None, description="Filter by function (substring search)"),
    department: Optional[str] = Query(None, description="Filter by department (substring search)"),
    keywords: Optional[str] = Query(None, description="Filter by keywords (substring search)"),
    db: Session = Depends(get_db),
    current_key: models.APIKey = Depends(require_read_permission)
) -> Union[List[schemas.JobSearchResult], schemas.JobStatistics]:
    """
    Get jobs with optional filters OR statistics (requires read permission).

    Set statistics=true to get job statistics by company and date instead of job list.
    All filters are optional and can be combined (filters are ignored when statistics=true).

    Args:
        statistics: If true, return statistics instead of job list
        company_name: Filter by company name (exact match)
        company_id: Filter by company ID
        found_on_date: Filter by scrape date - only jobs found on this date
        title_contains: Include only jobs with this substring in title
        title_excludes: Exclude jobs with this substring in title
        level: Filter by level (exact match)
        contract_type: Filter by contract type (exact match)
        location: Filter by location (substring search across location fields)
        function: Filter by function (substring search)
        department: Filter by department (substring search)
        keywords: Filter by keywords (substring search)
        current_key: Current authenticated API key (must have read)

    Returns:
        List of jobs matching the filters OR statistics object
    """
    try:
        # Return statistics if requested
        if statistics:
            companies_data = services.JobService.get_jobs_statistics(db, current_key)
            return schemas.JobStatistics(companies=companies_data)

        # Otherwise return filtered jobs
        results = services.JobService.get_jobs_with_filters(
            db=db,
            api_key=current_key,
            company_name=company_name,
            company_id=company_id,
            found_on_date=found_on_date,
            title_contains=title_contains,
            title_excludes=title_excludes,
            level=level,
            contract_type=contract_type,
            location=location,
            function=function,
            department=department,
            keywords=keywords
        )

        # Convert results to JobSearchResult format
        job_results = []
        for job, company in results:
            job_results.append(schemas.JobSearchResult(
                id=job.id,
                company_name=company.name,
                title=job.title,
                level=job.level,
                contract_type=job.contract_type,
                location=job.work_location_short or job.work_location
            ))

        return job_results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs/search", response_model=List[schemas.JobSearchResult])
def search_jobs(
    q: str,
    db: Session = Depends(get_db),
    current_key: models.APIKey = Depends(require_read_permission)
):
    """
    Search jobs by full-text search across title, function, and keywords (requires read permission).

    Args:
        q: Search query string
        current_key: Current authenticated API key (must have read)

    Returns:
        List of jobs matching the search query with selected fields
    """
    try:
        results = services.JobService.search_jobs(db, q, current_key)

        # Convert results to JobSearchResult format
        search_results = []
        for job, company in results:
            search_results.append(schemas.JobSearchResult(
                id=job.id,
                company_name=company.name,
                title=job.title,
                level=job.level,
                contract_type=job.contract_type,
                location=job.work_location_short or job.work_location
            ))

        return search_results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs/{job_id}", response_model=schemas.JobDetail)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_key: models.APIKey = Depends(require_read_permission)
):
    """
    Get a single job by ID with full details (requires read permission).

    Args:
        job_id: Job ID
        current_key: Current authenticated API key (must have read)

    Returns:
        Job details with all available information
    """
    try:
        result = services.JobService.get_job_by_id(db, job_id, current_key)

        if not result:
            raise HTTPException(status_code=404, detail=f"Job with ID {job_id} not found")

        job, company = result

        # Convert to JobDetail format
        job_detail = schemas.JobDetail(
            id=job.id,
            company_name=company.name,
            job_id=job.job_id,
            url=job.url,
            title=job.title,
            function=job.function,
            level=job.level,
            contract_type=job.contract_type,
            work_location=job.work_location,
            work_location_short=job.work_location_short,
            all_locations=job.all_locations,
            country=job.country,
            department=job.department,
            flexibility=job.flexibility,
            keywords=job.keywords,
            description=job.description,
            tasks=job.tasks,
            qualifications=job.qualifications,
            offerings=job.offerings,
            contact_person=job.contact_person,
            contact_email=job.contact_email,
            contact_phone=job.contact_phone,
            date_added=job.date_added,
            created_at=job.created_at,
            updated_at=job.updated_at
        )

        return job_detail
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, forwarded_allow_ips="*")
