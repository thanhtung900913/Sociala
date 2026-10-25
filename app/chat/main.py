from flask import Flask

from app.auth.utils.extensions import jwt
from app.chat.config import Config
from app.chat.db.connection import init_db_pool
from app.auth.utils.error_handlers import register_error_handlers
from app.chat.routes.conversation_route import conversation_bp
from app.chat.routes.realtime_route import realtime_bp, sock

app = Flask(__name__)

app.config.from_object(Config)
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = False
app.config["JWT_REFRESH_COOKIE_NAME"] = "refresh_token"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False

init_db_pool(app)
jwt.init_app(app)
register_error_handlers(app)

app.register_blueprint(conversation_bp, url_prefix='/api/v1/conversations')
app.register_blueprint(realtime_bp, url_prefix='/api/v1/realtime')
sock.init_app(app)


if __name__ == '__main__':
    app.run(debug=True)