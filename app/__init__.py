from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os, time
from dotenv import load_dotenv

load_dotenv()

# Força fuso horário de Brasília (UTC-3) no servidor Linux
os.environ['TZ'] = 'America/Sao_Paulo'
try:
    time.tzset()
except AttributeError:
    pass  # Windows não tem tzset, ignora

db = SQLAlchemy()
login_manager = LoginManager()

def _run_migrations(db):
    """Adiciona colunas novas em tabelas existentes sem quebrar dados."""
    migrations = [
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS source VARCHAR(16) DEFAULT 'loja'",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS app_name VARCHAR(64)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brands(id)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS image_data BYTEA",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS image_mime VARCHAR(32)",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS amount_paid FLOAT",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS change_amount FLOAT",
        "ALTER TABLE cash_registers ADD COLUMN IF NOT EXISTS closing_data TEXT",
    ]
    with db.engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(db.text(sql))
                conn.commit()
            except Exception:
                conn.rollback()

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
    from app.routes.account import account_bp
    from app.routes.apps import apps_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(master_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(cash_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(apps_bp)

    with app.app_context():
        app.logger.warning(f"[DB] vars: VENDIX={bool(os.environ.get('VENDIX_DB_URL'))} PUB={bool(os.environ.get('DATABASE_PUBLIC_URL'))} DB={bool(os.environ.get('DATABASE_URL'))}")
        app.logger.warning(f"[DB] Config URI = {app.config['SQLALCHEMY_DATABASE_URI'][:40]}...")
        db.create_all()
        _run_migrations(db)
        from app.seed import seed_master
        seed_master()

    return app
