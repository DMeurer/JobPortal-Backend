from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql://user:password@localhost:5432/jobportal"
    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "jobportal"
    database_user: str = "user"
    database_password: str = "password"

    # Fixed API Keys
    api_key_admin: str = "admin_key_change_me"
    api_key_webscraper: str = "webscraper_key_change_me"
    api_key_fullread: str = "fullread_key_change_me"
    api_key_frontend: str = "frontend_key_change_me"

    # Connection pool. Left at SQLAlchemy's defaults these caused two problems:
    # every pooled connection goes stale after a database restart and errors
    # until it is recycled, and exhaustion under concurrency makes requests hang
    # waiting for a connection with nothing in the access log to show for it.
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Recycle before typical proxy/database idle timeouts (30 minutes).
    db_pool_recycle: int = 1800
    # Seconds to wait for a free connection before failing loudly rather than
    # hanging indefinitely.
    db_pool_timeout: int = 30

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings():
    return Settings()
