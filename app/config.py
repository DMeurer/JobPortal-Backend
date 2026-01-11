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

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings():
    return Settings()
