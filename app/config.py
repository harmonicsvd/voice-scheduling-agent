import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    calendar_id: str = os.getenv("CALENDAR_ID", "")
    service_account_json: str | None = os.getenv("SERVICE_ACCOUNT_JSON")
    service_account_file: str = os.getenv("SERVICE_ACCOUNT_FILE", "service_account.json")

    google_oauth_client_id: str = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    google_oauth_client_secret: str = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    app_secret_key: str = os.getenv("APP_SECRET_KEY", "dev-secret")
    internal_api_key: str = os.getenv("INTERNAL_API_KEY", "")
    weather_agent_base_url: str = os.getenv("WEATHER_AGENT_BASE_URL", "").rstrip("/")
    weather_agent_internal_api_key: str = os.getenv("WEATHER_AGENT_INTERNAL_API_KEY", "")
    weather_agent_timeout_seconds: float = float(os.getenv("WEATHER_AGENT_TIMEOUT_SECONDS", "20"))

    vapi_public_key: str = os.getenv("VAPI_PUBLIC_KEY", "")
    app_db_path: str = os.getenv("APP_DB_PATH", "app.db")
    
   



settings = Settings()
