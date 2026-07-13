from datetime import datetime, timezone, timedelta
import os
import hashlib
from flask import Blueprint, jsonify, request, current_app
import bcrypt
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity, get_jwt
import psycopg2

from app.db.connection import get_db_connection
from app.models.auth_model import  RegisterRequestBody, LoginRequestBody
from app.utils.decorators import validate_payload
from app.utils.jwt_callbacks import BLOCKLIST

auth_bp = Blueprint('auth', __name__)
@auth_bp.route('/register', methods=['POST'])
@validate_payload(RegisterRequestBody)
def register(body: RegisterRequestBody):
    user = request.get_json(body)
    bytes_password = user.password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(bytes_password, salt).decode('utf-8')
    try:
        with get_db_connection() as conn:
            with conn.cursor as cur:
                # Create user in database
                cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)  RETURNING id", (user.username, hashed_password))
                user_id = cur.fetchone()[0]
                conn.commit()
        
        return jsonify({
            'message': 'User registered successfully',
            'user_id': user_id,
            'timestamp': datetime.now(timezone.utc).isoformat()
            }), 201
    except psycopg2.Error as e:
        current_app.logger.error("Database error occurred")
        return jsonify({"error": "Database error occurred"}), 500
    except Exception as e:
        current_app.logger.error("Internal server error")
        return jsonify({"error": "Internal server error"}), 500
            
@auth_bp.route("/login", methods=["POST"])
@validate_payload(LoginRequestBody)
def login(body: LoginRequestBody):
    try:
        with get_db_connection() as conn:
            with conn.cursor as cur:
                # Fetch user
                cur.execute(
                    """
                    SELECT id, username, password_hash
                    FROM public.users
                    WHERE username = %s
                    """,
                    (body.username,),
                )

                user_db = cur.fetchone()

                if not user_db:
                    return jsonify({
                        "message": "User not found",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }), 404

                user_id, username, password_hash = user_db

                # Verify password
                if not bcrypt.checkpw(
                    body.password.encode("utf-8"),
                    password_hash.encode("utf-8"),
                ):
                    return jsonify({
                        "message": "Password incorrect",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }), 400

                # Generate tokens
                access_token = create_access_token(identity=user_id)
                refresh_token = create_refresh_token(identity=user_id)
                hashed_refresh_token = hashlib.sha256(
                    refresh_token.encode("utf-8")
                ).hexdigest()

                # Upsert user device
                cur.execute(
                    """
                    INSERT INTO public.user_devices (id, user_id, device_info)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id)
                    DO UPDATE SET
                        device_info = EXCLUDED.device_info
                    WHERE user_devices.device_info IS DISTINCT FROM EXCLUDED.device_info
                    """,
                    (
                        body.device_id,
                        user_id,
                        body.device_info,
                    ),
                )

                # Revoke old refresh tokens
                cur.execute(
                    """
                    UPDATE public.refresh_tokens
                    SET is_revoked = true
                    WHERE user_id = %s
                      AND device_id = %s
                      AND is_revoked = false
                    """,
                    (
                        user_id,
                        body.device_id,
                    ),
                )

                # Save new refresh token
                cur.execute(
                    """
                    INSERT INTO public.refresh_tokens
                        (user_id, device_id, token_hash, expires_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        body.device_id,
                        hashed_refresh_token,
                        datetime.now(timezone.utc)
                        + timedelta(
                            seconds=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES"))
                        ),
                    ),
                )

                conn.commit()

        return jsonify({
            "message": f"Login success for user {username}",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except psycopg2.Error:
        current_app.logger.error("Database error occurred")
        return jsonify({"error": "Database error occurred"}), 500

    except Exception:
        current_app.logger.error("Internal server error")
        return jsonify({"error": "Internal server error"}), 500

@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    current_user_id = get_jwt_identity()
    new_access_token = create_access_token(identity=current_user_id)
    return jsonify({
        'access_token': new_access_token
    }), 200
    
@auth_bp.route('/logout', methods=['POST'])
@jwt_required(refresh=True)
def logout():
    jti = get_jwt()["jti"]
    BLOCKLIST.add(jti)
    return jsonify({
        'message': 'logout successful'
    }), 200