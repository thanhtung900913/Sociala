from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.backend.models.media_model import MediaUploadRequestBody
from app.backend.services.media import media_service
from app.backend.utils.decorators import validate_payload
from app.backend.utils.validation import parse_media_id


media_bp = Blueprint('media', __name__)


@media_bp.route('/upload', methods=['POST'])
@jwt_required(locations=["headers", "cookies"])
@validate_payload(MediaUploadRequestBody)
def upload_media(body: MediaUploadRequestBody):
    response = media_service.upload_media(get_jwt_identity(), body)
    return jsonify({"data": response.model_dump(mode="json")}), 200


@media_bp.route('/<media_id>/complete', methods=['POST'])
@jwt_required(locations=["headers", "cookies"])
def complete_media_upload(media_id: str):
    media_id = parse_media_id(media_id)
    response = media_service.complete_media_upload(get_jwt_identity(), media_id)
    return jsonify({"data": response.model_dump(mode="json")}), 200
