from datetime import datetime, timezone
import os
import secrets

import psycopg2
import requests
from flask import Blueprint, current_app, jsonify, redirect, request, session
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from app.models.auth_model import LoginRequestBody, RegisterRequestBody
from app.services import auth_service
from app.services.errors import ServiceError
from app.services.google_oauth import build_google_authorization_url
from app.utils.decorators import validate_payload

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["POST"])
@validate_payload(RegisterRequestBody)
def register(body: RegisterRequestBody):
    try:
        return jsonify(auth_service.register_user(body)), 201
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except psycopg2.Error:
        current_app.logger.exception("Database error during registration")
        return jsonify({"error": "Database error occurred"}), 500
    except Exception:
        current_app.logger.exception("Registration failed")
        return jsonify({"error": "Internal server error"}), 500


@auth_bp.route("/login", methods=["POST"])
@validate_payload(LoginRequestBody)
def login(body: LoginRequestBody):
    try:
        result = auth_service.login_user(
            body,
            user_agent=request.headers.get("User-Agent"),
            ip_address=request.remote_addr,
        )
        return jsonify(result), 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
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


@auth_bp.route("/google/callback", methods=["GET"])
def google_callback():
    try:
        state = request.args.get("state")
        code = request.args.get("code")
        if not state or state != session.pop("google_oauth_state", None):
            return jsonify({"message": "invalid oauth state"}), 400
        if not code:
            return jsonify({"message": "missing authorization code"}), 400

        result = auth_service.authenticate_google(
            code,
            user_agent=request.headers.get("User-Agent"),
            ip_address=request.remote_addr,
        )
        response = jsonify({"access_token": result["access_token"]})
        response.set_cookie(
            "refresh_token",
            result["refresh_token"],
            httponly=True,
            secure=False,
            samesite="Lax",
            max_age=int(os.getenv("REFRESH_TOKEN_EXPIRES_SECONDS", 2592000)),
            path="/api/v1/auth",
        )
        return response, 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
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
        result = auth_service.refresh_access_token(get_jwt_identity(), get_jwt()["sid"])
        return jsonify(result), 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except Exception:
        current_app.logger.exception("Refresh token failed")
        return jsonify({"message": "internal server error"}), 500


@auth_bp.route("/logout", methods=["POST"])
@jwt_required(refresh=True)
def logout():
    try:
        result = auth_service.logout_user(get_jwt_identity(), get_jwt()["sid"])
        return jsonify(result), 200
    except ServiceError as error:
        return jsonify(error.payload), error.status_code
    except Exception:
        current_app.logger.exception("Logout failed")
        return jsonify({"message": "internal server error"}), 500
