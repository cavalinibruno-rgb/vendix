from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///vendix_dev.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Faça login para acessar.'

    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.master import master_bp
    from app.routes.products import products_bp
    from app.routes.customers import customers_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(master_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(customers_bp)

    with app.app_context():
        uri = app.config['SQLALCHEMY_DATABASE_URI']
        app.logger.warning(f"[DB] Usando: {uri[:30]}...")
        db.create_all()
        from app.seed import seed_master
        seed_master()

    return app
