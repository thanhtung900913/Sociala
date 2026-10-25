from flask import Flask

from app.backend.utils.extensions import jwt
from app.backend.routes.media_route import media_bp
from app.backend.config import Config
from app.backend.db.connection import init_db_pool
from app.backend.utils.error_handlers import register_error_handlers
from app.backend.utils.celery_client import init_celery

app = Flask(__name__)

app.config.from_object(Config)
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = False
app.config["JWT_REFRESH_COOKIE_NAME"] = "refresh_token"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False

init_db_pool(app)
jwt.init_app(app)
register_error_handlers(app)
init_celery(app)

app.register_blueprint(media_bp, url_prefix='/api/v1/media')


if __name__ == '__main__':
    app.run(debug=True)