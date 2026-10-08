from app.services.auth_service import is_session_active
from app.utils.extensions import jwt

BLOCKLIST = set()


@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    if jwt_payload["jti"] in BLOCKLIST:
        return True
    session_id = jwt_payload.get("sid")
    if not session_id:
        return True
    return not is_session_active(jwt_payload["sub"], session_id)
