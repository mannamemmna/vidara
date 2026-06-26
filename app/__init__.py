from flask import Flask
from app.config import DL_DIR
import os

def create_app():
    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates'),
                static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'))
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'vidara-dev-key')

    # Ensure downloads dir
    os.makedirs(DL_DIR, exist_ok=True)

    # Register routes
    from app.routes import bp
    app.register_blueprint(bp)

    # CORS
    @app.after_request
    def add_cors(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
        return response

    return app
