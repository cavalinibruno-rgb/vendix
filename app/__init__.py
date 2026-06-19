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
    db_url = (
        os.environ.get('VENDIX_DB_URL') or
        os.environ.get('DATABASE_PUBLIC_URL') or
        os.environ.get('DATABASE_URL') or
        os.environ.get('POSTGRES_URL') or
        'sqlite:///vendix_dev.db'
    )
    # SQLAlchemy 2.x não aceita postgres://, converte para postgresql://
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
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
    from app.routes.sales import sales_bp
    from app.routes.cash import cash_bp
    from app.routes.stock import stock_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(master_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(cash_bp)
    app.register_blueprint(stock_bp)

    with app.app_context():
        app.logger.warning(f"[DB] vars: VENDIX={bool(os.environ.get('VENDIX_DB_URL'))} PUB={bool(os.environ.get('DATABASE_PUBLIC_URL'))} DB={bool(os.environ.get('DATABASE_URL'))}")
        app.logger.warning(f"[DB] Config URI = {app.config['SQLALCHEMY_DATABASE_URI'][:40]}...")
        db.create_all()
        from app.seed import seed_master
        seed_master()

    return app
