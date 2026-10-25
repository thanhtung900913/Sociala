from flask import Flask

from app.user.utils.extensions import jwt
from app.user.routes.user_route import user_bp
from app.user.routes.friend_request_route import friend_request_bp
from app.user.config import Config
from app.user.db.connection import init_db_pool
from app.user.utils.error_handlers import register_error_handlers

app = Flask(__name__)

app.config.from_object(Config)
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = False
app.config["JWT_REFRESH_COOKIE_NAME"] = "refresh_token"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False

init_db_pool(app)
jwt.init_app(app)
register_error_handlers(app)

app.register_blueprint(user_bp, url_prefix='/api/v1/users')
app.register_blueprint(friend_request_bp, url_prefix='/api/v1/friend-requests')


if __name__ == '__main__':
    app.run(debug=True)