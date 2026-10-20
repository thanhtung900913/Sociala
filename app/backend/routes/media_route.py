from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.backend.models.media_model import MediaUploadRequestBody
from app.backend.models.post_model import PostPageQuery
from app.backend.services import feed_service
from app.backend.utils.decorators import validate_payload, validate_query

media_bp = Blueprint('media', __name__)
@media_bp.route('/upload', methods=['POST'])
@jwt_required()
@validate_payload(MediaUploadRequestBody)
def upload_media(body: MediaUploadRequestBody):
    response = feed_service.upload_media(get_jwt_identity(), body)
    return jsonify({"data": response.model_dump(mode="json")}), 200