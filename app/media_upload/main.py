from flask import Flask

from app.media_upload.utils.extensions import jwt
from app.media_upload.routes.media_route import media_bp
from app.media_upload.config import Config
from app.media_upload.db.connection import init_db_pool
from app.media_upload.utils.error_handlers import register_error_handlers
from app.media_upload.utils.celery_client import init_celery

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