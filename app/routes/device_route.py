from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required
import psycopg2
from app.db.connection import get_db_connection
from app.models.device_model import DeviceRequestBody
from app.utils.decorators import validate_payload

device_bp = Blueprint('device', __name__)

@device_bp.route("", methods=["GET"])
@jwt_required()
def get_devices():
    try:
        with get_db_connection() as conn:
            with conn.cursor as cur:
                cur.execute(
                    """
                    SELECT id, device_name, device_info, device_id
                    FROM public.devices
                    """
                )

                devices = cur.fetchall()

        return jsonify({
            "data": devices,
            "message": "Devices retrieved successfully",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except psycopg2.Error:
        current_app.logger.error("Database error occurred")
        return jsonify({"error": "Database error occurred"}), 500

    except Exception:
        current_app.logger.error("Internal server error")
        return jsonify({"error": "Internal server error"}), 500
            
@device_bp.route("/", methods=["PATCH"])
@jwt_required(DeviceRequestBody)
@validate_payload()
def update_device(body: DeviceRequestBody):

    try:
        with get_db_connection() as conn:
            with conn.cursor as cur:
                cur.execute(
                    """
                    UPDATE public.devices
                    SET
                        device_info = %s,
                        is_disabled = %s
                    WHERE id = %s
                    """,
                    (
                        body.device_info,
                        body.is_disabled,
                        id,
                    ),
                )

                conn.commit()

        return jsonify({
            "message": f"Device updated successfully for device id: {id}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except psycopg2.Error:
        current_app.logger.error("Database error occurred")
        return jsonify({"error": "Database error occurred"}), 500

    except Exception:
        current_app.logger.error("Internal server error")
        return jsonify({"error": "Internal server error"}), 500
            
@device_bp.route("/<id>", methods=["DELETE"])
@jwt_required()
def delete_device(id):
    try:
        with get_db_connection() as conn:
            with conn.cursor as cur:
                # Disable device
                cur.execute(
                    """
                    UPDATE public.user_devices
                    SET is_disabled = true
                    WHERE id = %s
                    """,
                    (id,),
                )

                if cur.rowcount == 0:
                    return jsonify({
                        "message": "Device not found",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }), 404

                # Revoke all active refresh tokens of the device
                cur.execute(
                    """
                    UPDATE public.refresh_tokens
                    SET is_revoked = true
                    WHERE device_id = %s
                      AND is_revoked = false
                    """,
                    (id,),
                )

                conn.commit()

        return jsonify({
            "message": f"Device disabled successfully for device id: {id}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except psycopg2.Error:
        current_app.logger.error("Database error occurred")
        return jsonify({"error": "Database error occurred"}), 500

    except Exception:
        current_app.logger.error("Internal server error")
        return jsonify({"error": "Internal server error"}), 500