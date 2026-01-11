import secrets
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Date, Boolean, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    hidden = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    jobs = relationship("Job", back_populates="company")

    # Unique constraint on combination of name and hidden
    __table_args__ = (
        Index('ix_companies_name_hidden', 'name', 'hidden', unique=True),
    )


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # External identifiers
    job_id = Column(Text)
    url = Column(Text)
    url_title = Column(Text)

    # Job details
    title = Column(Text)
    function = Column(Text)
    level = Column(Text)
    contract_type = Column(Text)

    # Location information
    work_location = Column(Text)
    work_location_short = Column(Text)
    work_location_with_coordinates = Column(Text)
    all_locations = Column(Text)
    coordinates_primary = Column(Text)
    country = Column(Text)

    # Additional fields
    currency = Column(Text)
    supported_locales = Column(Text)
    department = Column(Text)
    flexibility = Column(Text)
    keywords = Column(Text)

    # Job description fields
    description = Column(Text)
    tasks = Column(Text)
    qualifications = Column(Text)
    offerings = Column(Text)

    # Contact information
    contact_person = Column(Text)
    contact_email = Column(Text)
    contact_phone = Column(Text)

    # Unified fields
    unified_url_title = Column(Text)
    unified_standard_end = Column(Text)
    unified_standard_start = Column(Text)

    # Metadata
    date_added = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    company = relationship("Company", back_populates="jobs")
    inserts = relationship("Insert", back_populates="job")


class Insert(Base):
    __tablename__ = "inserts"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    scrape_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="inserts")


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Permission flags
    admin = Column(Boolean, default=False, nullable=False)
    read = Column(Boolean, default=False, nullable=False)
    write = Column(Boolean, default=False, nullable=False)
    read_hidden = Column(Boolean, default=False, nullable=False)

    # Metadata
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Create composite index for performance
    __table_args__ = (
        Index('ix_api_keys_key_active', 'key', 'is_active'),
    )

    @staticmethod
    def generate_key() -> str:
        """Generate a cryptographically secure random API key."""
        return secrets.token_urlsafe(48)
