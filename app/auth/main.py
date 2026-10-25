from flask import Flask

from app.auth.utils.extensions import jwt
from app.auth.routes.auth_route import auth_bp
from app.auth.config import Config
from app.auth.db.connection import init_db_pool
from app.auth.utils.error_handlers import register_error_handlers

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


if __name__ == '__main__':
    app.run(debug=True)