from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional, List


class CompanyBase(BaseModel):
    name: str


class CompanyCreate(CompanyBase):
    pass


class Company(CompanyBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JobBase(BaseModel):
    company_name: str
    hidden: bool = False
    job_id: Optional[str] = None
    url: Optional[str] = None
    url_title: Optional[str] = None
    title: Optional[str] = None
    function: Optional[str] = None
    level: Optional[str] = None
    contract_type: Optional[str] = None
    work_location: Optional[str] = None
    work_location_short: Optional[str] = None
    work_location_with_coordinates: Optional[str] = None
    all_locations: Optional[str] = None
    coordinates_primary: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    supported_locales: Optional[str] = None
    department: Optional[str] = None
    flexibility: Optional[str] = None
    keywords: Optional[str] = None
    description: Optional[str] = None
    tasks: Optional[str] = None
    qualifications: Optional[str] = None
    offerings: Optional[str] = None
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    unified_url_title: Optional[str] = None
    unified_standard_end: Optional[str] = None
    unified_standard_start: Optional[str] = None
    date_added: Optional[date] = None


class JobCreate(JobBase):
    pass


class Job(BaseModel):
    id: int
    company_id: int
    job_id: Optional[str] = None
    url: Optional[str] = None
    url_title: Optional[str] = None
    title: Optional[str] = None
    function: Optional[str] = None
    level: Optional[str] = None
    contract_type: Optional[str] = None
    work_location: Optional[str] = None
    work_location_short: Optional[str] = None
    work_location_with_coordinates: Optional[str] = None
    all_locations: Optional[str] = None
    coordinates_primary: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    supported_locales: Optional[str] = None
    department: Optional[str] = None
    flexibility: Optional[str] = None
    keywords: Optional[str] = None
    description: Optional[str] = None
    tasks: Optional[str] = None
    qualifications: Optional[str] = None
    offerings: Optional[str] = None
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    unified_url_title: Optional[str] = None
    unified_standard_end: Optional[str] = None
    unified_standard_start: Optional[str] = None
    date_added: Optional[date] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class InsertBase(BaseModel):
    scrape_date: date


class InsertCreate(InsertBase):
    job_id: int


class Insert(InsertBase):
    id: int
    job_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class JobInsertRequest(JobBase):
    scrape_date: Optional[date] = None


class JobInsertResponse(BaseModel):
    job_id: int
    insert_id: int
    is_new_job: bool
    message: str

    class Config:
        from_attributes = True


# API Key schemas
class APIKeyBase(BaseModel):
    name: str
    description: Optional[str] = None
    admin: bool = False
    read: bool = False
    write: bool = False
    read_hidden: bool = False


class APIKeyCreate(APIKeyBase):
    pass


class APIKeyCreateResponse(BaseModel):
    id: int
    key: str  # Only included in creation response
    name: str
    description: Optional[str] = None
    admin: bool
    read: bool
    write: bool
    read_hidden: bool
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class APIKey(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    admin: bool
    read: bool
    write: bool
    read_hidden: bool
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Job search and retrieval schemas
class JobSearchResult(BaseModel):
    id: int
    company_name: str
    title: Optional[str] = None
    level: Optional[str] = None
    contract_type: Optional[str] = None
    location: Optional[str] = None

    class Config:
        from_attributes = True


class JobDetail(BaseModel):
    id: int
    company_name: str
    job_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    function: Optional[str] = None
    level: Optional[str] = None
    contract_type: Optional[str] = None
    work_location: Optional[str] = None
    work_location_short: Optional[str] = None
    all_locations: Optional[str] = None
    country: Optional[str] = None
    department: Optional[str] = None
    flexibility: Optional[str] = None
    keywords: Optional[str] = None
    description: Optional[str] = None
    tasks: Optional[str] = None
    qualifications: Optional[str] = None
    offerings: Optional[str] = None
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    date_added: Optional[date] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Statistics schemas
class DateStatistics(BaseModel):
    date: date
    open_positions: int
    newly_added: int
    removed: int


class CompanyStatistics(BaseModel):
    company_name: str
    dates: List[DateStatistics]


class JobStatistics(BaseModel):
    companies: List[CompanyStatistics]


class PaginatedJobSearchResult(BaseModel):
    jobs: List[JobSearchResult]
    total: int
    skip: int
    limit: int

    class Config:
        from_attributes = True


class FilterOptions(BaseModel):
    companies: List[str]
    levels: List[str]
    functions: List[str]

    class Config:
        from_attributes = True
