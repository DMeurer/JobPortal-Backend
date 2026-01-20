from sqlalchemy.orm import Session
from datetime import date
from typing import Optional, List
from app import models, schemas
from app.sanitize import sanitize_like_pattern, sanitize_regex, sanitize_string


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
        db.commit()
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
        found_on_date: Optional[date] = None
    ) -> List[dict]:
        """
        Get job statistics grouped by company and date.

        For each company and date, calculates:
        - open_positions: Number of unique jobs found on that date
        - newly_added: Jobs on current date that weren't on previous date
        - removed: Jobs on previous date that aren't on current date

        Args:
            db: Database session
            api_key: API key to check hidden permissions
            company_name: Filter by company name (exact match)
            company_names: Filter by multiple company names
            found_on_date: Filter to only include this specific date

        Returns:
            List of dictionaries with company statistics (filtered by hidden status)
        """
        # Get all inserts with job and company information
        # We need the actual job IDs to compare between dates
        query = db.query(
            models.Company.name.label('company_name'),
            models.Insert.scrape_date.label('date'),
            models.Insert.job_id.label('job_id')
        ).join(
            models.Job,
            models.Insert.job_id == models.Job.id
        ).join(
            models.Company,
            models.Job.company_id == models.Company.id
        )

        # Apply hidden filter
        query = JobService._apply_hidden_filter(query, api_key)

        # Apply company filters
        if company_name:
            query = query.filter(models.Company.name == company_name)
        if company_names:
            query = query.filter(models.Company.name.in_(company_names))

        query = query.order_by(
            models.Company.name,
            models.Insert.scrape_date.desc()
        )

        results = query.all()

        # Group jobs by company and date
        company_date_jobs = {}
        for row in results:
            company_name = row.company_name
            scrape_date = row.date
            job_id = row.job_id

            if company_name not in company_date_jobs:
                company_date_jobs[company_name] = {}

            if scrape_date not in company_date_jobs[company_name]:
                company_date_jobs[company_name][scrape_date] = set()

            company_date_jobs[company_name][scrape_date].add(job_id)

        # Calculate statistics for each company
        result = []
        for comp_name, date_jobs in company_date_jobs.items():
            # Sort dates in descending order
            sorted_dates = sorted(date_jobs.keys(), reverse=True)

            dates_stats = []
            for i, current_date in enumerate(sorted_dates):
                # Skip dates that don't match the filter (if specified)
                if found_on_date and current_date != found_on_date:
                    continue

                current_jobs = date_jobs[current_date]
                open_positions = len(current_jobs)

                # Calculate newly added and removed compared to previous date
                # Find the previous date in the sorted list
                prev_idx = i + 1
                if prev_idx < len(sorted_dates):
                    previous_date = sorted_dates[prev_idx]
                    previous_jobs = date_jobs[previous_date]

                    newly_added = len(current_jobs - previous_jobs)
                    removed = len(previous_jobs - current_jobs)
                else:
                    # No previous date, all jobs are newly added
                    newly_added = open_positions
                    removed = 0

                dates_stats.append({
                    'date': current_date,
                    'open_positions': open_positions,
                    'newly_added': newly_added,
                    'removed': removed
                })

            # Only include company if it has matching dates
            if dates_stats:
                result.append({
                    'company_name': comp_name,
                    'dates': dates_stats
                })

        return result

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
