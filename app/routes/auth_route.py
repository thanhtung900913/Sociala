import os
import secrets

from flask import Blueprint, jsonify, redirect, request, session
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
    response = auth_service.register_user(body)
    return jsonify(response.model_dump(mode="json")), 201


@auth_bp.route("/login", methods=["POST"])
@validate_payload(LoginRequestBody)
def login(body: LoginRequestBody):
    response = auth_service.login_user(
        body, user_agent=request.headers.get("User-Agent"),
        ip_address=request.remote_addr,
    )
    return jsonify(response.model_dump(mode="json")), 200


@auth_bp.route("/google", methods=["GET"])
def google_login():
    state = secrets.token_urlsafe(32)
    session["google_oauth_state"] = state
    return redirect(build_google_authorization_url(state))


@auth_bp.route("/google/callback", methods=["GET"])
def google_callback():
    state = request.args.get("state")
    code = request.args.get("code")
    if not state or state != session.pop("google_oauth_state", None):
        raise ServiceError({"message": "invalid oauth state"}, 400)
    if not code:
        raise ServiceError({"message": "missing authorization code"}, 400)

    body, refresh_token = auth_service.authenticate_google(
        code, user_agent=request.headers.get("User-Agent"),
        ip_address=request.remote_addr,
    )
    response = jsonify(body.model_dump(mode="json"))
    response.set_cookie(
        "refresh_token", refresh_token, httponly=True, secure=False,
        samesite="Lax",
        max_age=int(os.getenv("REFRESH_TOKEN_EXPIRES_SECONDS", 2592000)),
        path="/api/v1/auth",
    )
    return response, 200


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    response = auth_service.refresh_access_token(
        get_jwt_identity(), get_jwt()["sid"]
    )
    return jsonify(response.model_dump(mode="json")), 200


@auth_bp.route("/logout", methods=["POST"])
@jwt_required(refresh=True)
def logout():
    response = auth_service.logout_user(get_jwt_identity(), get_jwt()["sid"])
    return jsonify(response.model_dump(mode="json")), 200
