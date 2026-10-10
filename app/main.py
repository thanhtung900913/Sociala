from flask import Flask

from app.utils.extensions import jwt
from app.utils import jwt_callbacks
from app.routes.auth_route import auth_bp
from app.routes.user_route import user_bp
from app.routes.friend_request_route import friend_request_bp
from app.routes.post_route import post_bp
from app.config import Config
from app.db.connection import init_db_pool
from app.utils.error_handlers import register_error_handlers

app = Flask(__name__)

app.config.from_object(Config)
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = False
app.config["JWT_REFRESH_COOKIE_NAME"] = "refresh_token"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False

init_db_pool(app)
jwt.init_app(app)
register_error_handlers(app)

app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
app.register_blueprint(user_bp, url_prefix='/api/v1/users')
app.register_blueprint(friend_request_bp, url_prefix='/api/v1/friend-requests')
app.register_blueprint(post_bp, url_prefix='/api/v1/posts')


if __name__ == '__main__':
    app.run(debug=True)
