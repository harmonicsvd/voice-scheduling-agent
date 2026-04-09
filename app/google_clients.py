import json
from authlib.integrations.starlette_client import OAuth
from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():
    if settings.service_account_json:
        service_account_info = json.loads(settings.service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=SCOPES,
        )
    else:
        credentials = service_account.Credentials.from_service_account_file(
            settings.service_account_file,
            scopes=SCOPES,
        )

    return build("calendar", "v3", credentials=credentials)


def build_oauth() -> OAuth:
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile https://www.googleapis.com/auth/calendar"
        },
    )
    return oauth
