from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import get_jwt_identity, jwt_required
import psycopg2

from app.db.connection import get_db_connection
from app.models.favourite_class_model import FavouriteClassRequestBody
from app.utils.decorators import validate_payload

favourite_class_bp = Blueprint('favourite_class', __name__)

@favourite_class_bp.route("/", methods=["POST"])
@jwt_required()
@validate_payload()
def add_favourite_class():
    class_id = request.args.get("class_id")
    user_id = get_jwt_identity
    try:
        with get_db_connection() as conn:
            with conn.cursor as cur:
                cur.execute(
                    """
                    INSERT INTO public.user_favourite_classes (user_id, class_id)
                    VALUES (%s, %s)
                    """,
                    (
                        user_id,
                        class_id,
                    ),
                )

                conn.commit()

        return jsonify({
            "message": "Favourite class added successfully",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 201

    except psycopg2.Error:
        current_app.logger.error("Database error occurred")
        return jsonify({"error": "Database error occurred"}), 500

    except Exception:
        current_app.logger.error("Internal server error")
        return jsonify({"error": "Internal server error"}), 500

@favourite_class_bp.route("/", methods=["GET"])
@jwt_required()
def get_favourite_classes():
    user_id = get_jwt_identity()

    try:
        with get_db_connection() as conn:
            with conn.cursor as cur:
                cur.execute(
                    """
                    SELECT class_id
                    FROM public.user_favourite_classes
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )

                favourite_classes = cur.fetchall()

        return jsonify({
            "data": favourite_classes,
            "message": "Favourite classes retrieved successfully",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except psycopg2.Error:
        current_app.logger.error("Database error occurred")
        return jsonify({"error": "Database error occurred"}), 500

    except Exception:
        current_app.logger.error("Internal server error")
        return jsonify({"error": "Internal server error"}), 500
            
@favourite_class_bp.route("/<class_id>", methods=["DELETE"])
@jwt_required()
def delete_favourite_class(class_id):
    user_id = get_jwt_identity()

    try:
        with get_db_connection() as conn:
            with conn.cursor as cur:
                cur.execute(
                    """
                    DELETE FROM public.user_favourite_classes
                    WHERE user_id = %s
                      AND class_id = %s
                    """,
                    (
                        user_id,
                        class_id,
                    ),
                )

                if cur.rowcount == 0:
                    return jsonify({
                        "message": "Favourite class not found",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }), 404

                conn.commit()

        return jsonify({
            "message": "Favourite class deleted successfully",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except psycopg2.Error:
        current_app.logger.error("Database error occurred")
        return jsonify({"error": "Database error occurred"}), 500

    except Exception:
        current_app.logger.error("Internal server error")
        return jsonify({"error": "Internal server error"}), 500