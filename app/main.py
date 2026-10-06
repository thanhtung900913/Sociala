from flask import Flask

from app.utils.extensions import jwt
from app.routes.auth_route import auth_bp
from app.config import Config
from app.db.connection import init_db_pool

app = Flask(__name__)

app.config.from_object(Config)
init_db_pool(app)
jwt.init_app(app)

app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')


if __name__ == '__main__':
    app.run(debug=True)