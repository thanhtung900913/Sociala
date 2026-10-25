from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.feed.models.post_model import PostPageQuery
from app.feed.services import feed_service
from app.feed.utils.decorators import validate_query

feed_bp = Blueprint("feed", __name__)


@feed_bp.route("", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(PostPageQuery)
def get_feed(query: PostPageQuery):
    """Get a page of the user's feed."""
    response = feed_service.get_feed(get_jwt_identity(), query)
    result = jsonify(response.model_dump(mode="json"))
    result.headers["Cache-Control"] = "private, no-store"
    return result, 200