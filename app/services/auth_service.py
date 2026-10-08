from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets

import bcrypt
from flask_jwt_extended import create_access_token, create_refresh_token

from app.db.connection import get_db_connection_context
from app.models.auth_model import LoginRequestBody, RegisterRequestBody
from app.services.errors import ServiceError
from app.services.google_oauth import (
    exchange_google_code,
    generate_username,
    verify_google_id_token,
)


def _create_session(cur, user_id, user_agent, ip_address, expires_at):
    cur.execute(
        """
        INSERT INTO public.auth_sessions (user_id, user_agent, ip_address, expires_at)
        VALUES (%(user_id)s, %(user_agent)s, %(ip_address)s, %(expires_at)s)
        RETURNING id
        """,
        {
            "user_id": user_id,
            "user_agent": user_agent,
            "ip_address": ip_address,
            "expires_at": expires_at,
        },
    )
    return cur.fetchone()["id"]


def _save_refresh_token(cur, session_id, refresh_token, expires_at):
    cur.execute(
        """
        INSERT INTO public.refresh_tokens (session_id, token_hash, expires_at)
        VALUES (%(session_id)s, %(token_hash)s, %(expires_at)s)
        """,
        {
            "session_id": session_id,
            "token_hash": hashlib.sha256(refresh_token.encode("utf-8")).digest(),
            "expires_at": expires_at,
        },
    )


def register_user(body: RegisterRequestBody):
    """Register an account and return its identifier."""
    hashed_password = bcrypt.hashpw(
        body.password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            # Create user in database
            cur.execute(
                """
                INSERT INTO users (email, username, password_hash)
                VALUES (%(email)s, %(username)s, %(password_hash)s)
                RETURNING id
                """,
                {
                    "email": body.email,
                    "username": body.username,
                    "password_hash": hashed_password,
                }
            )
            user_id = cur.fetchone()["id"]
        conn.commit()

    return {
        "message": "User registered successfully",
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def login_user(body: LoginRequestBody, user_agent=None, ip_address=None):
    """Verify credentials and create a session and tokens atomically."""
    now = datetime.now(timezone.utc)

    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            # 1. Find user
            cur.execute(
                """SELECT id, email, username, password_hash
                FROM public.users
                WHERE email = %(email)s""",
                {"email": body.email},
            )
            user_db = cur.fetchone()

            if not user_db:
                raise ServiceError(
                    {"message": "Invalid email or password", "timestamp": now.isoformat()},
                    401,
                )

            user_id, email, password_hash = (
                user_db["id"],
                user_db["email"],
                user_db["password_hash"],
            )

            # 2. Verify password
            if not bcrypt.checkpw(body.password.encode(), password_hash.encode()):
                raise ServiceError(
                    {"message": "Invalid email or password", "timestamp": now.isoformat()},
                    401,
                )

            # 3. Create auth session
            session_expires_at = now + timedelta(
                seconds=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES"))
            )

            session_id = _create_session(
                cur, user_id, user_agent, ip_address, session_expires_at
            )

            # 4. Generate tokens
            access_token = create_access_token(
                identity=str(user_id),
                additional_claims={"sid": str(session_id)},
            )
            refresh_token = create_refresh_token(
                identity=str(user_id),
                additional_claims={"sid": str(session_id)},
            )

            # 5. Save refresh token
            _save_refresh_token(cur, session_id, refresh_token, session_expires_at)

        conn.commit()

    return {
        "message": "Login successful",
        "user": {"id": str(user_id), "email": email},
        "access_token": access_token,
        "refresh_token": refresh_token,
        "session_id": str(session_id),
        "expires_at": session_expires_at.isoformat(),
        "timestamp": now.isoformat(),
    }


def authenticate_google(code, user_agent=None, ip_address=None):
    """Authenticate a Google account and persist its session and refresh token."""
    token_data = exchange_google_code(code)
    google_claims = verify_google_id_token(token_data["id_token"])

    google_sub = google_claims.get("sub")
    email = google_claims.get("email")
    email_verified = google_claims.get("email_verified", False)

    if not google_sub or not email:
        raise ServiceError({"message": "invalid google account"}, 400)

    if not email_verified:
        raise ServiceError({"message": "google email is not verified"}, 400)

    now = datetime.now(timezone.utc)

    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.email, u.username, u.status
                FROM public.user_identities ui
                JOIN public.users u ON u.id = ui.user_id
                WHERE ui.provider = 'google'
                  AND ui.provider_user_id = %(google_sub)s
                  AND u.deleted_at IS NULL
                """,
                {"google_sub": google_sub},
            )
            user_db = cur.fetchone()

            if user_db:
                user_id = user_db["id"]

                if user_db["status"] != "ACTIVE":
                    raise ServiceError({
                        "message": "account is not active"
                    }, 403)

            else:
                cur.execute(
                    """
                    SELECT id
                    FROM public.users
                    WHERE LOWER(email) = LOWER(%(email)s)
                      AND deleted_at IS NULL
                    """,
                    {"email": email},
                )
                existing_user = cur.fetchone()

                if existing_user:
                    raise ServiceError({
                        "message": "account already exists; "
                        "login with password and link Google"
                    }, 409)

                username = generate_username(email)

                cur.execute(
                    """
                    INSERT INTO public.users (
                        email,
                        username,
                        password_hash,
                        email_verified_at
                    )
                    VALUES (
                        %(email)s,
                        %(username)s,
                        NULL,
                        %(email_verified_at)s
                    )
                    RETURNING id
                    """,
                    {
                        "email": email,
                        "username": username,
                        "email_verified_at": now,
                    },
                )
                user_id = cur.fetchone()["id"]

                cur.execute(
                    """
                    INSERT INTO public.user_identities (
                        user_id,
                        provider,
                        provider_user_id
                    )
                    VALUES (
                        %(user_id)s,
                        'google',
                        %(google_sub)s
                    )
                    """,
                    {
                        "user_id": user_id,
                        "google_sub": google_sub,
                    },
                )

            session_expires_at = now + timedelta(
                seconds=int(os.getenv("SESSION_EXPIRES_SECONDS", 2592000))
            )

            session_id = _create_session(
                cur, user_id, user_agent, ip_address, session_expires_at
            )

            refresh_token = secrets.token_urlsafe(64)

            refresh_expires_at = now + timedelta(
                seconds=int(os.getenv("REFRESH_TOKEN_EXPIRES_SECONDS", 2592000))
            )

            _save_refresh_token(cur, session_id, refresh_token, refresh_expires_at)

            access_token = create_access_token(
                identity=str(user_id),
                additional_claims={
                    "sid": str(session_id),
                },
            )

        conn.commit()

    return {"access_token": access_token, "refresh_token": refresh_token}


def refresh_access_token(user_id, session_id):
    """Issue an access token for a valid session."""
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM auth_sessions
                WHERE id = %(session_id)s
                  AND user_id = %(user_id)s
                  AND revoked_at IS NULL
                  AND expires_at > NOW()
                """,
                {"session_id": session_id, "user_id": user_id},
            )
            if not cur.fetchone():
                raise ServiceError({"message": "session is invalid"}, 401)

            access_token = create_access_token(
                identity=user_id,
                additional_claims={"sid": session_id},
            )

            cur.execute(
                """
                UPDATE auth_sessions
                SET last_used_at = NOW()
                WHERE id = %(session_id)s
                """,
                {"session_id": session_id},
            )

        conn.commit()

    return {"access_token": access_token}


def logout_user(user_id, session_id):
    """Revoke the authenticated session."""
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = NOW()
                WHERE id = %(session_id)s
                  AND user_id = %(user_id)s
                  AND revoked_at IS NULL
                """,
                {"session_id": session_id, "user_id": user_id},
            )
        conn.commit()

    return {"message": "logout successful"}


def is_session_active(user_id, session_id):
    """Check whether a session and its account still accept tokens."""
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.id FROM public.auth_sessions s
                JOIN public.users u ON u.id = s.user_id
                WHERE s.id = %(session_id)s AND s.user_id = %(user_id)s
                  AND s.revoked_at IS NULL AND s.expires_at > NOW()
                  AND u.deleted_at IS NULL AND u.status = 'ACTIVE'
                """,
                {"session_id": session_id, "user_id": user_id},
            )
            return cur.fetchone() is not None
