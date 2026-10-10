from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.models.post_model import (
    CreateCommentRequestBody, CreatePostRequestBody, PostPageQuery,
    PutReactionRequestBody, ReactionsQuery, SharePostRequestBody,
    UpdatePostRequestBody,
)
from app.services import comment_service, post_service
from app.utils.decorators import validate_payload, validate_query
from app.utils.validation import parse_post_id

post_bp = Blueprint("post", __name__)


@post_bp.route("", methods=["POST"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(CreatePostRequestBody)
def create_post(body: CreatePostRequestBody):
    response = post_service.create_post(get_jwt_identity(), body)
    return jsonify({"data": response.model_dump(mode="json")}), 201, {
        "Location": f"/api/v1/posts/{response.id}",
    }


@post_bp.route("/<post_id>", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
def get_post(post_id):
    post_id = parse_post_id(post_id)
    response = post_service.get_post(get_jwt_identity(), post_id)
    return jsonify({"data": response.model_dump(mode="json")}), 200


@post_bp.route("/<post_id>", methods=["PATCH"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(UpdatePostRequestBody)
def update_post(body: UpdatePostRequestBody, post_id):
    post_id = parse_post_id(post_id)
    response = post_service.update_post(get_jwt_identity(), post_id, body)
    return jsonify({"data": response.model_dump(mode="json")}), 200


@post_bp.route("/<post_id>", methods=["DELETE"])
@jwt_required(locations=["headers", "cookies"])
def delete_post(post_id):
    post_id = parse_post_id(post_id)
    post_service.delete_post(get_jwt_identity(), post_id)
    return current_app.response_class(status=204)


@post_bp.route("/<post_id>/hidden", methods=["PUT"])
@jwt_required(locations=["headers", "cookies"])
def hide_post(post_id):
    post_id = parse_post_id(post_id)
    post_service.hide_post(get_jwt_identity(), post_id)
    return current_app.response_class(status=204)


@post_bp.route("/<post_id>/hidden", methods=["DELETE"])
@jwt_required(locations=["headers", "cookies"])
def unhide_post(post_id):
    post_id = parse_post_id(post_id)
    post_service.unhide_post(get_jwt_identity(), post_id)
    return current_app.response_class(status=204)


@post_bp.route("/<post_id>/shares", methods=["POST"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(SharePostRequestBody)
def share_post(body: SharePostRequestBody, post_id):
    post_id = parse_post_id(post_id)
    response = post_service.share_post(get_jwt_identity(), post_id, body)
    return jsonify({"data": response.model_dump(mode="json")}), 201, {
        "Location": f"/api/v1/posts/{response.id}",
    }


@post_bp.route("/<post_id>/shares", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(PostPageQuery)
def list_shares(query: PostPageQuery, post_id):
    post_id = parse_post_id(post_id)
    response = post_service.list_shares(get_jwt_identity(), post_id, query)
    return jsonify(response.model_dump(mode="json")), 200


@post_bp.route("/<post_id>/reaction", methods=["PUT"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(PutReactionRequestBody)
def put_reaction(body: PutReactionRequestBody, post_id):
    post_id = parse_post_id(post_id)
    response = post_service.put_reaction(get_jwt_identity(), post_id, body)
    return jsonify({"data": response.model_dump(mode="json")}), 200


@post_bp.route("/<post_id>/reaction", methods=["DELETE"])
@jwt_required(locations=["headers", "cookies"])
def remove_reaction(post_id):
    post_id = parse_post_id(post_id)
    post_service.remove_reaction(get_jwt_identity(), post_id)
    return current_app.response_class(status=204)


@post_bp.route("/<post_id>/reactions", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(ReactionsQuery)
def list_reactions(query: ReactionsQuery, post_id):
    post_id = parse_post_id(post_id)
    response = post_service.list_reactions(get_jwt_identity(), post_id, query)
    return jsonify(response.model_dump(mode="json")), 200


@post_bp.route("/<post_id>/comments", methods=["POST"])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(CreateCommentRequestBody)
def create_comment(body: CreateCommentRequestBody, post_id):
    post_id = parse_post_id(post_id)
    response = comment_service.create_comment(
        get_jwt_identity(), post_id, body
    )
    return jsonify({"data": response.model_dump(mode="json")}), 201, {
        "Location": f"/api/v1/comments/{response.id}",
    }


@post_bp.route("/<post_id>/comments", methods=["GET"])
@jwt_required(locations=["headers", "cookies"])
@validate_query(PostPageQuery)
def list_comments(query: PostPageQuery, post_id):
    post_id = parse_post_id(post_id)
    response = comment_service.list_comments(
        get_jwt_identity(), post_id, query
    )
    return jsonify(response.model_dump(mode="json")), 200
