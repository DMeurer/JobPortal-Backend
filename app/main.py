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


@app.get("/api/jobs/filters", response_model=schemas.FilterOptions)
def get_filter_options(
    db: Session = Depends(get_db),
    current_key: models.APIKey = Depends(require_read_permission)
):
    """
    Get available filter options for job search (requires read permission).

    Returns:
        FilterOptions with distinct companies, levels, and functions
    """
    try:
        options = services.JobService.get_filter_options(db, current_key)
        return schemas.FilterOptions(**options)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs")
def get_jobs(
    statistics: bool = Query(False, description="Return statistics instead of job list"),
    company_name: Optional[str] = Query(None, description="Filter by company name (exact match)"),
    company_names: Optional[str] = Query(None, description="Filter by multiple company names (comma-separated)"),
    company_id: Optional[int] = Query(None, description="Filter by company ID"),
    found_on_date: Optional[str] = Query(None, description="Filter by scrape date (YYYY-MM-DD or 'today')"),
    job_status: Optional[str] = Query(None, description="Filter by job status: 'new', 'existing', or 'removed' (requires found_on_date and company_name)"),
    title_contains: Optional[str] = Query(None, description="Filter jobs containing this substring in title"),
    title_excludes: Optional[str] = Query(None, description="Exclude jobs containing this substring in title"),
    title_regex: Optional[str] = Query(None, description="Filter jobs by regex pattern in title"),
    level: Optional[str] = Query(None, description="Filter by level (exact match)"),
    levels: Optional[str] = Query(None, description="Filter by multiple levels (comma-separated)"),
    contract_type: Optional[str] = Query(None, description="Filter by contract type (exact match)"),
    location: Optional[str] = Query(None, description="Filter by location (substring search)"),
    function: Optional[str] = Query(None, description="Filter by function (substring search)"),
    function_regex: Optional[str] = Query(None, description="Filter by regex pattern in function"),
    department: Optional[str] = Query(None, description="Filter by department (substring search)"),
    keywords: Optional[str] = Query(None, description="Filter by keywords (substring search)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_key: models.APIKey = Depends(require_read_permission)
) -> Union[schemas.PaginatedJobSearchResult, schemas.JobStatistics]:
    """
    Get jobs with optional filters OR statistics (requires read permission).

    Set statistics=true to get job statistics by company and date instead of job list.
    All filters are optional and can be combined (filters are ignored when statistics=true).

    Args:
        statistics: If true, return statistics instead of job list
        company_name: Filter by company name (exact match)
        company_names: Filter by multiple company names (comma-separated)
        company_id: Filter by company ID
        found_on_date: Filter by scrape date (YYYY-MM-DD or 'today') - only jobs found on this date
        job_status: Filter by job status on the given date:
            - 'new': Jobs that appeared on this date (not on previous date)
            - 'existing': Jobs that existed on both this date and previous date
            - 'removed': Jobs on this date that don't appear on the next date
        title_contains: Include only jobs with this substring in title
        title_excludes: Exclude jobs with this substring in title
        title_regex: Filter by regex pattern in title (PostgreSQL regex)
        level: Filter by level (exact match)
        levels: Filter by multiple levels (comma-separated)
        contract_type: Filter by contract type (exact match)
        location: Filter by location (substring search across location fields)
        function: Filter by function (substring search)
        function_regex: Filter by regex pattern in function (PostgreSQL regex)
        department: Filter by department (substring search)
        keywords: Filter by keywords (substring search)
        skip: Number of records to skip (for pagination)
        limit: Maximum number of records to return
        current_key: Current authenticated API key (must have read)

    Returns:
        Paginated list of jobs matching the filters OR statistics object
    """
    try:
        # Parse comma-separated values
        company_names_list = [c.strip() for c in company_names.split(',')] if company_names else None
        levels_list = [l.strip() for l in levels.split(',')] if levels else None

        # Parse found_on_date - accept "today" or YYYY-MM-DD format
        parsed_found_on_date = None
        if found_on_date:
            if found_on_date.lower() == "today":
                parsed_found_on_date = date.today()
            else:
                try:
                    parsed_found_on_date = date.fromisoformat(found_on_date)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD or 'today'")

        # Return statistics if requested
        if statistics:
            companies_data = services.JobService.get_jobs_statistics(
                db=db,
                api_key=current_key,
                company_name=company_name,
                company_names=company_names_list,
                found_on_date=parsed_found_on_date
            )
            return schemas.JobStatistics(companies=companies_data)

        # Return filtered jobs
        results, total = services.JobService.get_jobs_with_filters(
            db=db,
            api_key=current_key,
            company_name=company_name,
            company_names=company_names_list,
            company_id=company_id,
            found_on_date=parsed_found_on_date,
            job_status=job_status,
            title_contains=title_contains,
            title_excludes=title_excludes,
            title_regex=title_regex,
            level=level,
            levels=levels_list,
            contract_type=contract_type,
            location=location,
            function=function,
            function_regex=function_regex,
            department=department,
            keywords=keywords,
            skip=skip,
            limit=limit
        )

        # Convert results to JobSearchResult format
        job_results = []
        for job, company, first_seen, last_seen in results:
            job_results.append(schemas.JobSearchResult(
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
                date_added=job.date_added,
                first_seen=first_seen,
                last_seen=last_seen
            ))

        return schemas.PaginatedJobSearchResult(
            jobs=job_results,
            total=total,
            skip=skip,
            limit=limit or total
        )
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
        for job, company, first_seen, last_seen in results:
            search_results.append(schemas.JobSearchResult(
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
                date_added=job.date_added,
                first_seen=first_seen,
                last_seen=last_seen
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

def statistics_job_open_time():
    """
    Example function to demonstrate additional functionality.
    This function could be expanded to calculate job open times.
    """
    pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, forwarded_allow_ips="*")
