from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional, List
from app import models, schemas
from app.sanitize import sanitize_like_pattern, sanitize_regex, sanitize_string


# Statistics are computed entirely in the database. The previous implementation
# loaded every (company, date, job_id) insert row into Python and did the set
# arithmetic there; on ~240k rows that cost ~2.7s of pure Python per request
# while the underlying scan takes ~200ms.
#
# Semantics that must be preserved exactly:
#   * Grouping is by company NAME, not id. `companies` has a unique index on
#     (name, hidden), so one name can map to two rows (e.g. a hidden and a
#     visible variant) and the original code merged them via a dict keyed on
#     name. `name_key` reproduces that by collapsing every id sharing a name
#     onto the smallest such id, while keeping join keys integral.
#   * "Previous date" means the previous date that exists FOR THAT NAME, not
#     the previous calendar day.
#   * A company's first date reports newly_added = open_positions, removed = 0.
#   * found_on_date filters the OUTPUT only; the diff against the previous date
#     is still computed from the full history.
#   * Duplicate (job, date) inserts collapse. create_insert() already dedupes in
#     application code, but nothing in the schema enforces it, so DISTINCT stays.
#
# `removed` uses a set identity rather than a second 240k-row join:
#     removed(d) = |P \ D| = |P| - |P n D| = open(prev) - open(d) + new(d)
# which reduces it to a LAG over the ~1.8k-row aggregate.
# Statistics are served from the `company_date_statistics` materialized view
# (migration d5a9c71e3f82), which holds one row per scope, company and date.
# Filtering it is an indexed scan of a few thousand rows instead of recomputing
# the whole history from ~240k insert rows on every request.
#
# The view carries an `include_hidden` dimension because the numbers are not
# permission-independent: `companies` has a unique index on (name, hidden), so
# one name can be two rows which the API merges by name. An admin sees both
# halves combined, a public key sees only the visible half, and those are
# genuinely different numbers for the same (name, date).
#
# Everything else is pure row selection: company filters, the date window and
# found_on_date all narrow the output without changing any value, because
# newly_added/removed were computed in the view against the true previous scrape
# date for that company.
_JOB_STATISTICS_SQL = text("""
SELECT
    company_name,
    scrape_date,
    open_positions,
    newly_added,
    removed
FROM company_date_statistics
WHERE include_hidden = :include_hidden
  AND (CAST(:company_name AS varchar) IS NULL OR company_name = :company_name)
  AND (CAST(:company_names AS varchar[]) IS NULL
       OR company_name = ANY(CAST(:company_names AS varchar[])))
  AND (CAST(:found_on_date AS date) IS NULL OR scrape_date = :found_on_date)
  AND (CAST(:date_from AS date) IS NULL OR scrape_date >= :date_from)
  AND (CAST(:date_to AS date) IS NULL OR scrape_date <= :date_to)
ORDER BY company_name, scrape_date DESC
""")


# Rebuild the materialized view. CONCURRENTLY keeps it readable throughout, at
# the cost of needing the unique index the migration creates.
_REFRESH_STATISTICS_SQL = text(
    "REFRESH MATERIALIZED VIEW CONCURRENTLY company_date_statistics"
)

# CONCURRENTLY cannot populate a view that has never been populated, so a first
# refresh (or one after a manual TRUNCATE-like reset) falls back to this.
_REFRESH_STATISTICS_BLOCKING_SQL = text(
    "REFRESH MATERIALIZED VIEW company_date_statistics"
)

# Records when the view was last rebuilt. Health checks compare this against the
# newest insert to decide whether the dashboard is showing current numbers.
_MARK_STATISTICS_REFRESHED_SQL = text("""
INSERT INTO statistics_refresh (id, refreshed_at)
VALUES (true, now())
ON CONFLICT (id) DO UPDATE SET refreshed_at = now()
""")


# Everything /health/data needs, in one round trip.
#
# last_insert_at is when data most recently LANDED, which is the honest measure
# of "did the scrapers run" - scrape_date is a calendar date and cannot express
# an age in hours. stale compares that against the refresh marker rather than
# comparing max(scrape_date), which would miss a re-run that adds rows to a date
# already present.
_STATISTICS_HEALTH_SQL = text("""
SELECT
    (SELECT max(created_at) FROM inserts)                       AS last_insert_at,
    (SELECT max(scrape_date) FROM inserts)                      AS last_scrape_date,
    (SELECT refreshed_at FROM statistics_refresh LIMIT 1)       AS refreshed_at,
    (SELECT count(*) FROM company_date_statistics)              AS view_rows,
    EXTRACT(EPOCH FROM (now() - (SELECT max(created_at) FROM inserts))) / 3600.0
                                                                AS data_age_hours
""")


class JobService:
    """Service layer for job-related operations."""

    @staticmethod
    def _apply_hidden_filter(query, api_key: Optional[models.APIKey] = None):
        """
        Apply hidden company filter to a query based on API key permissions.

        If the API key has read_hidden permission or is admin, no filtering is applied.
        Otherwise, filter out hidden companies.

        Args:
            query: SQLAlchemy query to filter
            api_key: API key to check permissions (if None, filter hidden companies)

        Returns:
            Filtered query
        """
        # If no API key or API key doesn't have read_hidden permission, filter hidden companies
        if not api_key or (not api_key.read_hidden and not api_key.admin):
            query = query.filter(models.Company.hidden == False)
        return query

    @staticmethod
    def get_or_create_company(db: Session, company_name: str, hidden: bool = False) -> models.Company:
        """
        Get existing company or create a new one.

        Companies are identified by the combination of name and hidden flag.
        This allows the same company name to exist as both hidden and non-hidden entities.

        Args:
            db: Database session
            company_name: Name of the company
            hidden: Whether the company is hidden (default: False)

        Returns:
            Company model instance
        """
        company = db.query(models.Company).filter(
            models.Company.name == company_name,
            models.Company.hidden == hidden
        ).first()

        if not company:
            company = models.Company(name=company_name, hidden=hidden)
            db.add(company)
            db.commit()
            db.refresh(company)

        return company

    @staticmethod
    def find_existing_job(
        db: Session,
        company_id: int,
        job_id: Optional[str] = None,
        url: Optional[str] = None
    ) -> Optional[models.Job]:
        """
        Find existing job by company_id and either job_id or url.

        Args:
            db: Database session
            company_id: Company ID
            job_id: External job ID
            url: Job URL

        Returns:
            Job model instance if found, None otherwise
        """
        query = db.query(models.Job).filter(models.Job.company_id == company_id)

        if job_id:
            query = query.filter(models.Job.job_id == job_id)
        elif url:
            query = query.filter(models.Job.url == url)
        else:
            return None

        return query.first()

    @staticmethod
    def create_or_update_job(
        db: Session,
        job_data: schemas.JobInsertRequest
    ) -> tuple[models.Job, bool]:
        """
        Create a new job or update existing one.

        Args:
            db: Database session
            job_data: Job data to insert/update

        Returns:
            Tuple of (Job instance, is_new flag)
        """
        company = JobService.get_or_create_company(db, job_data.company_name, job_data.hidden)

        existing_job = JobService.find_existing_job(
            db,
            company.id,
            job_data.job_id,
            job_data.url
        )

        is_new = existing_job is None

        if is_new:
            job = models.Job(
                company_id=company.id,
                job_id=job_data.job_id,
                url=job_data.url,
                url_title=job_data.url_title,
                title=job_data.title,
                function=job_data.function,
                level=job_data.level,
                contract_type=job_data.contract_type,
                work_location=job_data.work_location,
                work_location_short=job_data.work_location_short,
                work_location_with_coordinates=job_data.work_location_with_coordinates,
                all_locations=job_data.all_locations,
                coordinates_primary=job_data.coordinates_primary,
                country=job_data.country,
                currency=job_data.currency,
                supported_locales=job_data.supported_locales,
                department=job_data.department,
                flexibility=job_data.flexibility,
                keywords=job_data.keywords,
                description=job_data.description,
                tasks=job_data.tasks,
                qualifications=job_data.qualifications,
                offerings=job_data.offerings,
                contact_person=job_data.contact_person,
                contact_email=job_data.contact_email,
                contact_phone=job_data.contact_phone,
                unified_url_title=job_data.unified_url_title,
                unified_standard_end=job_data.unified_standard_end,
                unified_standard_start=job_data.unified_standard_start,
                date_added=job_data.date_added or date.today()
            )
            db.add(job)
            db.commit()
            db.refresh(job)
        else:
            job = existing_job

        return job, is_new

    @staticmethod
    def create_insert(
        db: Session,
        job_id: int,
        scrape_date: date
    ) -> Optional[models.Insert]:
        """
        Create a new insert record if it doesn't exist for this job and date.

        Args:
            db: Database session
            job_id: Job ID
            scrape_date: Date of the scrape

        Returns:
            Insert model instance if created, None if already exists
        """
        existing_insert = db.query(models.Insert).filter(
            models.Insert.job_id == job_id,
            models.Insert.scrape_date == scrape_date
        ).first()

        if existing_insert:
            return None

        insert = models.Insert(
            job_id=job_id,
            scrape_date=scrape_date
        )
        db.add(insert)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent scraper inserted the same (job_id, scrape_date)
            # between the check above and this commit. The unique index added in
            # b7e1a4c92f03 turns that race into an error instead of a duplicate
            # row, and the outcome the caller cares about - the row exists - is
            # already true, so this is reported the same way as "already exists".
            db.rollback()
            return None
        db.refresh(insert)

        return insert

    @staticmethod
    def insert_job(
        db: Session,
        job_data: schemas.JobInsertRequest
    ) -> schemas.JobInsertResponse:
        """
        Main method to insert or update a job and create an insert record.

        Args:
            db: Database session
            job_data: Job data to insert

        Returns:
            JobInsertResponse with results
        """
        job, is_new = JobService.create_or_update_job(db, job_data)

        scrape_date = job_data.scrape_date or date.today()
        insert = JobService.create_insert(db, job.id, scrape_date)

        if insert:
            message = "New job created with insert record" if is_new else "Existing job found, new insert record created"
            return schemas.JobInsertResponse(
                job_id=job.id,
                insert_id=insert.id,
                is_new_job=is_new,
                message=message
            )
        else:
            message = "Job and insert record already exist for this date" if not is_new else "New job created but insert record already exists for this date"
            existing_insert = db.query(models.Insert).filter(
                models.Insert.job_id == job.id,
                models.Insert.scrape_date == scrape_date
            ).first()
            return schemas.JobInsertResponse(
                job_id=job.id,
                insert_id=existing_insert.id if existing_insert else -1,
                is_new_job=is_new,
                message=message
            )

    @staticmethod
    def get_all_companies(db: Session, api_key: Optional[models.APIKey] = None) -> List[models.Company]:
        """
        Get all companies from the database.

        Args:
            db: Database session
            api_key: API key to check hidden permissions

        Returns:
            List of Company instances (filtered by hidden status)
        """
        query = db.query(models.Company)
        query = JobService._apply_hidden_filter(query, api_key)
        return query.all()

    @staticmethod
    def search_jobs(db: Session, search_query: str, api_key: Optional[models.APIKey] = None) -> List[tuple]:
        """
        Search jobs by full-text search across title, function, and keywords.

        Args:
            db: Database session
            search_query: Search query string
            api_key: API key to check hidden permissions

        Returns:
            List of tuples with (Job, Company, first_seen, last_seen) instances (filtered by hidden status)
        """
        from sqlalchemy import or_, func as sql_func

        # Subqueries for first_seen and last_seen dates
        first_seen_subq = db.query(
            models.Insert.job_id,
            sql_func.min(models.Insert.scrape_date).label('first_seen')
        ).group_by(models.Insert.job_id).subquery()

        last_seen_subq = db.query(
            models.Insert.job_id,
            sql_func.max(models.Insert.scrape_date).label('last_seen')
        ).group_by(models.Insert.job_id).subquery()

        # Sanitize search query for LIKE pattern
        sanitized_query = sanitize_like_pattern(sanitize_string(search_query))
        search_pattern = f"%{sanitized_query}%" if sanitized_query else "%"

        query = db.query(
            models.Job,
            models.Company,
            first_seen_subq.c.first_seen,
            last_seen_subq.c.last_seen
        ).join(
            models.Company,
            models.Job.company_id == models.Company.id
        ).outerjoin(
            first_seen_subq,
            models.Job.id == first_seen_subq.c.job_id
        ).outerjoin(
            last_seen_subq,
            models.Job.id == last_seen_subq.c.job_id
        ).filter(
            or_(
                models.Job.title.ilike(search_pattern, escape='\\'),
                models.Job.function.ilike(search_pattern, escape='\\'),
                models.Job.keywords.ilike(search_pattern, escape='\\')
            )
        )

        query = JobService._apply_hidden_filter(query, api_key)
        return query.all()

    @staticmethod
    def get_job_by_id(db: Session, job_id: int, api_key: Optional[models.APIKey] = None) -> Optional[tuple]:
        """
        Get a single job by ID with company information.

        Args:
            db: Database session
            job_id: Job ID
            api_key: API key to check hidden permissions

        Returns:
            Tuple of (Job, Company) if found and accessible, None otherwise
        """
        query = db.query(models.Job, models.Company).join(
            models.Company,
            models.Job.company_id == models.Company.id
        ).filter(
            models.Job.id == job_id
        )

        query = JobService._apply_hidden_filter(query, api_key)
        return query.first()

    @staticmethod
    def _get_adjacent_date(db: Session, company_name: str, current_date: date, direction: str, api_key: Optional[models.APIKey] = None) -> Optional[date]:
        """
        Get the previous or next scrape date for a company.

        Args:
            db: Database session
            company_name: Company name to filter by
            current_date: The reference date
            direction: 'previous' or 'next'
            api_key: API key to check hidden permissions

        Returns:
            Adjacent date or None if not found
        """
        from sqlalchemy import func as sql_func

        query = db.query(models.Insert.scrape_date).join(
            models.Job,
            models.Insert.job_id == models.Job.id
        ).join(
            models.Company,
            models.Job.company_id == models.Company.id
        ).filter(
            models.Company.name == company_name
        )

        query = JobService._apply_hidden_filter(query, api_key)

        if direction == 'previous':
            query = query.filter(models.Insert.scrape_date < current_date).order_by(models.Insert.scrape_date.desc())
        else:
            query = query.filter(models.Insert.scrape_date > current_date).order_by(models.Insert.scrape_date.asc())

        result = query.first()
        return result[0] if result else None

    @staticmethod
    def _get_job_ids_on_date(db: Session, company_name: str, target_date: date, api_key: Optional[models.APIKey] = None) -> set:
        """
        Get all job IDs for a company on a specific date.

        Args:
            db: Database session
            company_name: Company name to filter by
            target_date: The date to check
            api_key: API key to check hidden permissions

        Returns:
            Set of job IDs
        """
        query = db.query(models.Job.id).join(
            models.Company,
            models.Job.company_id == models.Company.id
        ).join(
            models.Insert,
            models.Job.id == models.Insert.job_id
        ).filter(
            models.Company.name == company_name,
            models.Insert.scrape_date == target_date
        )

        query = JobService._apply_hidden_filter(query, api_key)
        return {r[0] for r in query.all()}

    @staticmethod
    def get_jobs_with_filters(
        db: Session,
        api_key: Optional[models.APIKey] = None,
        company_name: Optional[str] = None,
        company_names: Optional[List[str]] = None,
        company_id: Optional[int] = None,
        found_on_date: Optional[date] = None,
        job_status: Optional[str] = None,
        title_contains: Optional[str] = None,
        title_excludes: Optional[str] = None,
        title_regex: Optional[str] = None,
        level: Optional[str] = None,
        levels: Optional[List[str]] = None,
        contract_type: Optional[str] = None,
        location: Optional[str] = None,
        function: Optional[str] = None,
        function_regex: Optional[str] = None,
        department: Optional[str] = None,
        keywords: Optional[str] = None,
        skip: int = 0,
        limit: Optional[int] = None,
        count_only: bool = False
    ) -> tuple[List[tuple], int]:
        """
        Get jobs with optional filters.

        Args:
            db: Database session
            api_key: API key to check hidden permissions
            company_name: Filter by company name (exact match)
            company_names: Filter by multiple company names
            company_id: Filter by company ID
            found_on_date: Filter by scrape date (jobs found on this date)
            job_status: Filter by job status on the date: 'new', 'existing', 'removed'
                - 'new': Jobs on this date that weren't on the previous date
                - 'existing': Jobs on this date that were also on the previous date
                - 'removed': Jobs on this date that aren't on the next date
            title_contains: Filter jobs that contain this substring in title
            title_excludes: Filter out jobs that contain this substring in title
            title_regex: Filter jobs by regex pattern in title
            level: Filter by level (exact match)
            levels: Filter by multiple levels
            contract_type: Filter by contract type (exact match)
            location: Filter by location (substring search in work_location or work_location_short)
            function: Filter by function (substring search)
            function_regex: Filter by regex pattern in function
            department: Filter by department (substring search)
            keywords: Filter by keywords (substring search)
            skip: Number of records to skip (for pagination)
            limit: Maximum number of records to return
            count_only: If True, only return the count

        Returns:
            Tuple of (List of tuples with (Job, Company) instances, total count)
        """
        from sqlalchemy import and_, or_, func as sql_func
        from sqlalchemy.orm import aliased

        # Subqueries for first_seen and last_seen dates
        first_seen_subq = db.query(
            models.Insert.job_id,
            sql_func.min(models.Insert.scrape_date).label('first_seen')
        ).group_by(models.Insert.job_id).subquery()

        last_seen_subq = db.query(
            models.Insert.job_id,
            sql_func.max(models.Insert.scrape_date).label('last_seen')
        ).group_by(models.Insert.job_id).subquery()

        # Handle job_status filtering which requires comparing dates
        job_id_filter = None
        query_date = found_on_date  # The date to actually query jobs from
        if found_on_date and job_status and company_name:
            current_job_ids = JobService._get_job_ids_on_date(db, company_name, found_on_date, api_key)

            if job_status == 'new':
                # Jobs on current date that weren't on the previous date
                prev_date = JobService._get_adjacent_date(db, company_name, found_on_date, 'previous', api_key)
                if prev_date:
                    prev_job_ids = JobService._get_job_ids_on_date(db, company_name, prev_date, api_key)
                    job_id_filter = current_job_ids - prev_job_ids
                else:
                    # No previous date, all jobs are "new"
                    job_id_filter = current_job_ids
            elif job_status == 'existing':
                # Jobs on current date that were also on the previous date
                prev_date = JobService._get_adjacent_date(db, company_name, found_on_date, 'previous', api_key)
                if prev_date:
                    prev_job_ids = JobService._get_job_ids_on_date(db, company_name, prev_date, api_key)
                    job_id_filter = current_job_ids & prev_job_ids
                else:
                    # No previous date, no "existing" jobs
                    job_id_filter = set()
            elif job_status == 'removed':
                # "Removed" on date X means: jobs that were on the PREVIOUS date but NOT on date X
                # So we need to query from the previous date and filter to jobs not on current date
                prev_date = JobService._get_adjacent_date(db, company_name, found_on_date, 'previous', api_key)
                if prev_date:
                    prev_job_ids = JobService._get_job_ids_on_date(db, company_name, prev_date, api_key)
                    # Jobs on previous date that are NOT on current date
                    job_id_filter = prev_job_ids - current_job_ids
                    # Query from the previous date since that's where these jobs exist
                    query_date = prev_date
                else:
                    # No previous date, no jobs are considered "removed"
                    job_id_filter = set()

        # Base query with company join and first_seen/last_seen
        query = db.query(
            models.Job,
            models.Company,
            first_seen_subq.c.first_seen,
            last_seen_subq.c.last_seen
        ).join(
            models.Company,
            models.Job.company_id == models.Company.id
        ).outerjoin(
            first_seen_subq,
            models.Job.id == first_seen_subq.c.job_id
        ).outerjoin(
            last_seen_subq,
            models.Job.id == last_seen_subq.c.job_id
        )

        # If filtering by date, need to join with Insert table
        # Use query_date which may differ from found_on_date for 'removed' status
        if found_on_date:
            query = query.join(
                models.Insert,
                models.Job.id == models.Insert.job_id
            ).filter(models.Insert.scrape_date == query_date)

        # Apply job_id_filter if we have one from job_status
        if job_id_filter is not None:
            if len(job_id_filter) == 0:
                # No matching jobs, return empty result
                return [], 0
            query = query.filter(models.Job.id.in_(job_id_filter))

        # Apply filters
        if company_name:
            query = query.filter(models.Company.name == company_name)

        if company_names:
            query = query.filter(models.Company.name.in_(company_names))

        if company_id:
            query = query.filter(models.Company.id == company_id)

        if title_contains:
            sanitized = sanitize_like_pattern(sanitize_string(title_contains))
            query = query.filter(models.Job.title.ilike(f"%{sanitized}%", escape='\\'))

        if title_excludes:
            sanitized = sanitize_like_pattern(sanitize_string(title_excludes))
            query = query.filter(~models.Job.title.ilike(f"%{sanitized}%", escape='\\'))

        if title_regex:
            sanitized = sanitize_regex(sanitize_string(title_regex))
            query = query.filter(models.Job.title.op('~*')(sanitized))

        if level:
            query = query.filter(models.Job.level == level)

        if levels:
            query = query.filter(models.Job.level.in_(levels))

        if contract_type:
            query = query.filter(models.Job.contract_type == contract_type)

        if location:
            sanitized = sanitize_like_pattern(sanitize_string(location))
            query = query.filter(
                or_(
                    models.Job.work_location.ilike(f"%{sanitized}%", escape='\\'),
                    models.Job.work_location_short.ilike(f"%{sanitized}%", escape='\\'),
                    models.Job.all_locations.ilike(f"%{sanitized}%", escape='\\')
                )
            )

        if function:
            sanitized = sanitize_like_pattern(sanitize_string(function))
            query = query.filter(models.Job.function.ilike(f"%{sanitized}%", escape='\\'))

        if function_regex:
            sanitized = sanitize_regex(sanitize_string(function_regex))
            query = query.filter(models.Job.function.op('~*')(sanitized))

        if department:
            sanitized = sanitize_like_pattern(sanitize_string(department))
            query = query.filter(models.Job.department.ilike(f"%{sanitized}%", escape='\\'))

        if keywords:
            sanitized = sanitize_like_pattern(sanitize_string(keywords))
            query = query.filter(models.Job.keywords.ilike(f"%{sanitized}%", escape='\\'))

        # Apply hidden filter based on API key permissions
        query = JobService._apply_hidden_filter(query, api_key)

        # Use distinct() in case found_on_date creates duplicates
        if found_on_date:
            query = query.distinct()

        # Get total count before pagination
        total = query.count()

        if count_only:
            return [], total

        # Apply pagination
        query = query.offset(skip)
        if limit:
            query = query.limit(limit)

        return query.all(), total

    @staticmethod
    def get_jobs_statistics(
        db: Session,
        api_key: Optional[models.APIKey] = None,
        company_name: Optional[str] = None,
        company_names: Optional[List[str]] = None,
        found_on_date: Optional[date] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None
    ) -> List[dict]:
        """
        Get job statistics grouped by company and date.

        For each company and date, calculates:
        - open_positions: Number of unique jobs found on that date
        - newly_added: Jobs on current date that weren't on previous date
        - removed: Jobs on previous date that aren't on current date

        The aggregation runs in the database (see _JOB_STATISTICS_SQL); this
        function only reshapes the flat result into the nested per-company form.

        Args:
            db: Database session
            api_key: API key to check hidden permissions
            company_name: Filter by company name (exact match)
            company_names: Filter by multiple company names
            found_on_date: Filter to only include this specific date. Applied to
                the output only - newly_added/removed are still computed against
                the true previous scrape date.
            date_from: Only report dates >= this. newly_added/removed for the
                first reported date are still computed against the last scrape
                date before it, so a narrow window does not report every open
                position as newly added.
            date_to: Only report dates <= this.

        Returns:
            List of dictionaries with company statistics (filtered by hidden status)
        """
        # Mirrors _apply_hidden_filter: admin or read_hidden sees hidden companies,
        # and selects which of the view's two scopes to read.
        include_hidden = bool(api_key and (api_key.read_hidden or api_key.admin))

        rows = db.execute(
            _JOB_STATISTICS_SQL,
            {
                "include_hidden": include_hidden,
                "company_name": company_name,
                "company_names": list(company_names) if company_names else None,
                "found_on_date": found_on_date,
                "date_from": date_from,
                "date_to": date_to,
            },
        ).all()

        # Rows arrive ordered by company_name, then scrape_date DESC, so a single
        # pass builds the nested structure without any sorting or lookups.
        result: List[dict] = []
        current_name = None
        dates_stats: List[dict] = []

        for row in rows:
            if row.company_name != current_name:
                if dates_stats:
                    result.append({
                        'company_name': current_name,
                        'dates': dates_stats
                    })
                current_name = row.company_name
                dates_stats = []

            dates_stats.append({
                'date': row.scrape_date,
                'open_positions': row.open_positions,
                'newly_added': row.newly_added,
                'removed': row.removed
            })

        # Only include company if it has matching dates
        if dates_stats:
            result.append({
                'company_name': current_name,
                'dates': dates_stats
            })

        return result

    @staticmethod
    def refresh_statistics(db: Session) -> dict:
        """
        Rebuild the company_date_statistics materialized view.

        Must be run after new inserts land, otherwise the dashboard keeps
        serving the previous scrape's numbers. Safe to run at any time - it is a
        full recompute from `inserts`, so it repairs the view no matter how it
        got out of step.

        Returns:
            {'rows': int, 'concurrent': bool} describing what was rebuilt.
        """
        try:
            # CONCURRENTLY leaves the view readable while it rebuilds, so
            # requests during a refresh see the old data rather than an error.
            db.execute(_REFRESH_STATISTICS_SQL)
            db.commit()
            concurrent = True
        except Exception:
            # CONCURRENTLY refuses to populate a view that has never been
            # populated. Fall back to the blocking form, which briefly locks
            # readers but always works.
            db.rollback()
            db.execute(_REFRESH_STATISTICS_BLOCKING_SQL)
            db.commit()
            concurrent = False

        rows = db.execute(
            text("SELECT count(*) FROM company_date_statistics")
        ).scalar()

        # Record the rebuild so health checks can tell whether the view is behind
        # the data it summarises.
        db.execute(_MARK_STATISTICS_REFRESHED_SQL)
        db.commit()

        return {'rows': int(rows or 0), 'concurrent': concurrent}

    @staticmethod
    def statistics_health(db: Session, max_age_hours: float) -> dict:
        """
        Report whether the statistics the dashboard serves are trustworthy.

        Two independent failure modes, both invisible from the UI:
          - the scrapers stopped running, so the data is old
          - the scrapers ran but the view was not refreshed, so the dashboard
            keeps serving the previous run's numbers

        Args:
            db: Database session
            max_age_hours: how old the newest data may be before it counts as stale

        Returns:
            dict with 'healthy' plus the details behind the verdict
        """
        row = db.execute(_STATISTICS_HEALTH_SQL).one()

        problems = []

        if row.last_insert_at is None:
            # An empty database is reported as unhealthy rather than quietly OK:
            # "no data at all" is exactly the condition monitoring should catch.
            problems.append('no scrape data')
            age_hours = None
        else:
            age_hours = float(row.data_age_hours)
            if age_hours > max_age_hours:
                problems.append(
                    f'newest data is {age_hours:.1f}h old (limit {max_age_hours:.0f}h)'
                )

        # The view is behind if data landed after the last rebuild. A missing
        # marker means it has never been refreshed through the application.
        stale = False
        if row.last_insert_at is not None:
            if row.refreshed_at is None:
                stale = True
                problems.append('statistics have never been refreshed')
            elif row.last_insert_at > row.refreshed_at:
                stale = True
                problems.append('statistics are behind the data')

        return {
            'healthy': not problems,
            'problems': problems,
            'last_scrape_date': row.last_scrape_date,
            'last_insert_at': row.last_insert_at,
            'statistics_refreshed_at': row.refreshed_at,
            'statistics_rows': int(row.view_rows or 0),
            'data_age_hours': round(age_hours, 1) if age_hours is not None else None,
            'max_age_hours': max_age_hours,
            'statistics_stale': stale,
        }

    def get_statistics_online_time(self, db: Session, company_name: Optional[str] = None):
        """
        Get statistics on how long jobs have been online for each company.

        Args:
            db: Database session
            company_name: Optional company name to filter results
        Returns:
            List of dictionaries with job online time statistics
        """
        """
        SQL query would be:
        
        SELECT online_duration as online_days, COUNT(id) AS job_count
        FROM
            (SELECT recent.id, recent.scrape_date AS recent_date, oldest.scrape_date AS oldest_date,
                (recent.scrape_date - oldest.scrape_date) AS online_duration
            FROM
                (SELECT j.id, max(i.scrape_date) as scrape_date
                FROM inserts i, jobs j
                WHERE
                    i.job_id = j.id
                GROUP BY j.id) AS recent,
                (SELECT j.id , min(i.scrape_date) as scrape_date
                FROM inserts i, jobs j
                WHERE
                    i.job_id = j.id
                GROUP BY j.id) AS oldest
            WHERE recent.id = oldest.id
                AND recent.scrape_date > oldest.scrape_date
            ) as durations
        WHERE durations.recent_date != '2026-01-12'
        GROUP BY online_duration
        ORDER BY online_duration DESC;
        """
        return ""

    @staticmethod
    def get_filter_options(db: Session, api_key: Optional[models.APIKey] = None) -> dict:
        """
        Get distinct values for filter dropdowns.

        Args:
            db: Database session
            api_key: API key to check hidden permissions

        Returns:
            Dictionary with lists of distinct companies, levels, and functions
        """
        from sqlalchemy import distinct

        # Get companies
        company_query = db.query(distinct(models.Company.name)).join(
            models.Job,
            models.Company.id == models.Job.company_id
        )
        company_query = JobService._apply_hidden_filter(company_query, api_key)
        companies = [c[0] for c in company_query.all() if c[0]]
        companies.sort()

        # Get levels
        level_query = db.query(distinct(models.Job.level)).join(
            models.Company,
            models.Job.company_id == models.Company.id
        )
        level_query = JobService._apply_hidden_filter(level_query, api_key)
        levels = [l[0] for l in level_query.all() if l[0]]
        levels.sort()

        # Get functions
        function_query = db.query(distinct(models.Job.function)).join(
            models.Company,
            models.Job.company_id == models.Company.id
        )
        function_query = JobService._apply_hidden_filter(function_query, api_key)
        functions = [f[0] for f in function_query.all() if f[0]]
        functions.sort()

        return {
            'companies': companies,
            'levels': levels,
            'functions': functions
        }


class APIKeyService:
    """Service layer for API key-related operations."""

    @staticmethod
    def create_api_key(
        db: Session,
        api_key_data: schemas.APIKeyCreate
    ) -> models.APIKey:
        """
        Create a new API key with generated secure token.

        Args:
            db: Database session
            api_key_data: API key configuration

        Returns:
            APIKey model instance with generated key
        """
        api_key = models.APIKey(
            key=models.APIKey.generate_key(),
            name=api_key_data.name,
            description=api_key_data.description,
            admin=api_key_data.admin,
            read=api_key_data.read,
            write=api_key_data.write,
            read_hidden=api_key_data.read_hidden,
            is_active=True
        )
        db.add(api_key)
        db.commit()
        db.refresh(api_key)
        return api_key

    @staticmethod
    def get_api_key_by_key(db: Session, key: str) -> Optional[models.APIKey]:
        """
        Retrieve an API key by its key value.

        Args:
            db: Database session
            key: The API key string

        Returns:
            APIKey instance if found and active, None otherwise
        """
        return db.query(models.APIKey).filter(
            models.APIKey.key == key,
            models.APIKey.is_active == True
        ).first()

    @staticmethod
    def update_last_used(db: Session, api_key: models.APIKey) -> None:
        """
        Update the last_used_at timestamp for an API key.

        Args:
            db: Database session
            api_key: APIKey instance
        """
        from datetime import datetime
        api_key.last_used_at = datetime.utcnow()
        db.commit()

    @staticmethod
    def verify_permission(api_key: models.APIKey, permission: str) -> bool:
        """
        Check if an API key has a specific permission.

        Args:
            api_key: APIKey instance
            permission: Permission name ('admin', 'read', or 'write')

        Returns:
            True if key has permission, False otherwise
        """
        if not api_key.is_active:
            return False

        # Admin has all permissions
        if api_key.admin:
            return True

        return getattr(api_key, permission, False)

    @staticmethod
    def get_all_api_keys(db: Session) -> List[models.APIKey]:
        """
        Get all API keys (for admin listing).

        Args:
            db: Database session

        Returns:
            List of APIKey instances
        """
        return db.query(models.APIKey).all()