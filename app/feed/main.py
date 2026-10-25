from flask import Flask

from app.feed.utils.extensions import jwt
from app.feed.routes.post_route import post_bp
from app.feed.routes.feed_route import feed_bp
from app.feed.config import Config
from app.feed.db.connection import init_db_pool
from app.feed.utils.error_handlers import register_error_handlers

app = Flask(__name__)

app.config.from_object(Config)
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = False
app.config["JWT_REFRESH_COOKIE_NAME"] = "refresh_token"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False

init_db_pool(app)
jwt.init_app(app)
register_error_handlers(app)

app.register_blueprint(post_bp, url_prefix='/api/v1/posts')
app.register_blueprint(feed_bp, url_prefix='/api/v1/feed')

if __name__ == '__main__':
    app.run(debug=True)
