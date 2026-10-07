from datetime import datetime, timezone, timedelta
import os
import hashlib
from flask import Blueprint, jsonify, request, current_app
import bcrypt
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity, get_jwt
import secrets
from flask import redirect, session
import requests
from app.services.google_oauth import build_google_authorization_url, generate_username
import psycopg2

from app.db.connection import get_db_connection
from app.models.auth_model import  RegisterRequestBody, LoginRequestBody
from app.utils.decorators import validate_payload
from app.utils.jwt_callbacks import BLOCKLIST

auth_bp = Blueprint('auth', __name__)
@auth_bp.route('/register', methods=['POST'])
@validate_payload(RegisterRequestBody)
def register(body: RegisterRequestBody):
    bytes_password = body.password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(bytes_password, salt).decode('utf-8')
    try:
        with get_db_connection() as conn:
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
                user_id = cur.fetchone()['id']
                conn.commit()
        
        return jsonify({
            'message': 'User registered successfully',
            'user_id': user_id,
            'timestamp': datetime.now(timezone.utc).isoformat()
            }), 201
    except psycopg2.Error as e:
        current_app.logger.error(f"Database error occurred: {e}")
        return jsonify({"error": "Database error occurred"}), 500
    except Exception as e:
        current_app.logger.error(f"Internal server error: {e}")
        # current_app.logger.error(f"Internal server error: {e}")
        return jsonify({"error": "Internal server error"}), 500
            
@auth_bp.route("/login", methods=["POST"])
@validate_payload(LoginRequestBody)
def login(body):
    try:
        now = datetime.now(timezone.utc)

        with get_db_connection() as conn:
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
                    return jsonify({"message": "Invalid email or password", "timestamp": now.isoformat()}), 401

                user_id, email, password_hash = (
                    user_db["id"],
                    user_db["email"],
                    user_db["password_hash"],
                )

                # 2. Verify password
                if not bcrypt.checkpw(body.password.encode(), password_hash.encode()):
                    return jsonify({"message": "Invalid email or password", "timestamp": now.isoformat()}), 401

                # 3. Create auth session
                session_expires_at = now + timedelta(
                    seconds=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES"))
                )
                user_agent = request.headers.get("User-Agent")
                ip_address = request.remote_addr

                cur.execute(
                    """INSERT INTO public.auth_sessions (
                        user_id, user_agent, ip_address, expires_at
                    ) VALUES (
                        %(user_id)s, %(user_agent)s, %(ip_address)s, %(expires_at)s
                    ) RETURNING id""",
                    {
                        "user_id": user_id,
                        "user_agent": user_agent,
                        "ip_address": ip_address,
                        "expires_at": session_expires_at,
                    },
                )
                session_id = cur.fetchone()["id"]

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
                token_hash = hashlib.sha256(refresh_token.encode()).digest()
                cur.execute(
                    """INSERT INTO public.refresh_tokens (
                        session_id, token_hash, expires_at
                    ) VALUES (
                        %(session_id)s, %(token_hash)s, %(expires_at)s
                    ) RETURNING id""",
                    {
                        "session_id": session_id,
                        "token_hash": token_hash,
                        "expires_at": session_expires_at,
                    },
                )
                refresh_token_id = cur.fetchone()["id"]

                conn.commit()

        return jsonify({
            "message": "Login successful",
            "user": {"id": str(user_id), "email": email},
            "access_token": access_token,
            "refresh_token": refresh_token,
            "session_id": str(session_id),
            "expires_at": session_expires_at.isoformat(),
            "timestamp": now.isoformat(),
        }), 200

    except psycopg2.Error:
        current_app.logger.exception("Database error during login")
        return jsonify({
            "error": "Database error occurred",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 500

    except Exception:
        current_app.logger.exception("Internal server error during login")
        return jsonify({
            "error": "Internal server error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 500

@auth_bp.route("/google", methods=["GET"])
def google_login():
    state = secrets.token_urlsafe(32)
    session["google_oauth_state"] = state

    return redirect(build_google_authorization_url(state))

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from flask import jsonify, request, session
from flask_jwt_extended import create_access_token

from app.services.google_oauth import (
    exchange_google_code,
    verify_google_id_token,
)


@auth_bp.route("/google/callback", methods=["GET"])
def google_callback():
    try:
        state = request.args.get("state")
        code = request.args.get("code")

        if not state or state != session.pop("google_oauth_state", None):
            return jsonify({"message": "invalid oauth state"}), 400

        if not code:
            return jsonify({"message": "missing authorization code"}), 400

        token_data = exchange_google_code(code)
        google_claims = verify_google_id_token(token_data["id_token"])

        google_sub = google_claims.get("sub")
        email = google_claims.get("email")
        email_verified = google_claims.get("email_verified", False)

        if not google_sub or not email:
            return jsonify({"message": "invalid google account"}), 400

        if not email_verified:
            return jsonify({"message": "google email is not verified"}), 400

        now = datetime.now(timezone.utc)
        user_agent = request.headers.get("User-Agent")
        ip_address = request.remote_addr

        with get_db_connection() as conn:
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
                        return jsonify({
                            "message": "account is not active"
                        }), 403

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
                        return jsonify({
                            "message": "account already exists; "
                            "login with password and link Google"
                        }), 409

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

                cur.execute(
                    """
                    INSERT INTO public.auth_sessions (
                        user_id,
                        user_agent,
                        ip_address,
                        expires_at
                    )
                    VALUES (
                        %(user_id)s,
                        %(user_agent)s,
                        %(ip_address)s,
                        %(expires_at)s
                    )
                    RETURNING id
                    """,
                    {
                        "user_id": user_id,
                        "user_agent": user_agent,
                        "ip_address": ip_address,
                        "expires_at": session_expires_at,
                    },
                )
                session_id = cur.fetchone()["id"]

                refresh_token = secrets.token_urlsafe(64)
                token_hash = hashlib.sha256(
                    refresh_token.encode("utf-8")
                ).digest()

                refresh_expires_at = now + timedelta(
                    seconds=int(os.getenv("REFRESH_TOKEN_EXPIRES_SECONDS", 2592000))
                )

                cur.execute(
                    """
                    INSERT INTO public.refresh_tokens (
                        session_id,
                        token_hash,
                        expires_at
                    )
                    VALUES (
                        %(session_id)s,
                        %(token_hash)s,
                        %(expires_at)s
                    )
                    """,
                    {
                        "session_id": session_id,
                        "token_hash": token_hash,
                        "expires_at": refresh_expires_at,
                    },
                )

                access_token = create_access_token(
                    identity=str(user_id),
                    additional_claims={
                        "sid": str(session_id),
                    },
                )

            conn.commit()

        response = jsonify({
            "access_token": access_token,
        })

        response.set_cookie(
            "refresh_token",
            refresh_token,
            httponly=True,
            secure=False,
            samesite="Lax",
            max_age=int(os.getenv("REFRESH_TOKEN_EXPIRES_SECONDS", 2592000)),
            path="/api/v1/auth",
        )

        return response, 200

    except requests.RequestException:
        current_app.logger.exception("Google token exchange failed")
        return jsonify({"message": "google authentication failed"}), 502

    except Exception:
        current_app.logger.exception("Google callback failed")
        return jsonify({"message": "internal server error"}), 500

@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    try:
        user_id = get_jwt_identity()
        session_id = get_jwt()["sid"]

        with get_db_connection() as conn:
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
                    return jsonify({"message": "session is invalid"}), 401

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

        return jsonify({"access_token": access_token}), 200

    except Exception:
        current_app.logger.exception("Refresh token failed")
        return jsonify({"message": "internal server error"}), 500
    
@auth_bp.route("/logout", methods=["POST"])
@jwt_required(refresh=True)
def logout():
    try:
        user_id = get_jwt_identity()
        session_id = get_jwt()["sid"]

        with get_db_connection() as conn:
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

        return jsonify({"message": "logout successful"}), 200

    except Exception:
        current_app.logger.exception("Logout failed")
        return jsonify({"message": "internal server error"}), 500