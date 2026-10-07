import os
import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = "openid email profile"


def build_google_authorization_url(state):
    params = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI"),
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }

    response = requests.Request(
        "GET",
        GOOGLE_AUTH_URL,
        params=params,
    ).prepare()

    return response.url


def exchange_google_code(code):
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI"),
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def verify_google_id_token(token):
    return id_token.verify_oauth2_token(
        token,
        google_requests.Request(),
        os.getenv("GOOGLE_CLIENT_ID"),
    )

import re
import secrets


def generate_username(email):
    base = re.sub(r"[^A-Za-z0-9_]", "", email.split("@")[0])[:20]
    base = base or "user"
    return f"{base}_{secrets.token_hex(4)}"[:30]