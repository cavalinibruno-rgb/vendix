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
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS thumbnail_data BYTEA",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS settings TEXT DEFAULT '{}'",
        """CREATE TABLE IF NOT EXISTS motoboys (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) NOT NULL,
            name VARCHAR(128) NOT NULL,
            phone VARCHAR(32),
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMP",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS motoboy_id INTEGER REFERENCES motoboys(id)",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS motoboy_name VARCHAR(128)",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS source VARCHAR(16) DEFAULT 'loja'",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS app_name VARCHAR(64)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brands(id)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS image_data BYTEA",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS image_mime VARCHAR(32)",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS amount_paid FLOAT",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS change_amount FLOAT",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS cancelled_by_id INTEGER REFERENCES users(id)",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS cancelled_by_name VARCHAR(64)",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS cancel_reason TEXT",
        "ALTER TABLE cash_registers ADD COLUMN IF NOT EXISTS closing_data TEXT",
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS role VARCHAR(32) DEFAULT 'caixa'",
        "ALTER TABLE cash_registers ADD COLUMN IF NOT EXISTS operator_employee_id INTEGER REFERENCES employees(id)",
        "ALTER TABLE cash_registers ADD COLUMN IF NOT EXISTS operator_name VARCHAR(128)",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS cashier_name VARCHAR(128)",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP",
        """CREATE TABLE IF NOT EXISTS cash_withdrawals (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) NOT NULL,
            cash_register_id INTEGER REFERENCES cash_registers(id) NOT NULL,
            amount FLOAT NOT NULL,
            motivo VARCHAR(256) NOT NULL,
            operator_name VARCHAR(128) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS username VARCHAR(64)",
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS password_hash VARCHAR(256)",
        """CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) NOT NULL,
            date DATE NOT NULL,
            category VARCHAR(64) NOT NULL,
            description VARCHAR(256),
            amount FLOAT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS cost_price FLOAT DEFAULT 0",
        "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS cost_price FLOAT DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS combo_items (
            id SERIAL PRIMARY KEY,
            combo_id INTEGER REFERENCES products(id) NOT NULL,
            component_id INTEGER REFERENCES products(id) NOT NULL,
            quantity FLOAT NOT NULL DEFAULT 1
        )""",
        """CREATE TABLE IF NOT EXISTS employees (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) NOT NULL,
            name VARCHAR(128) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS stock_movements (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) NOT NULL,
            product_id INTEGER REFERENCES products(id),
            product_name VARCHAR(128) NOT NULL,
            type VARCHAR(8) NOT NULL,
            quantity INTEGER NOT NULL,
            motive VARCHAR(128),
            user_id INTEGER REFERENCES users(id),
            user_name VARCHAR(64),
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS vales (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) NOT NULL,
            employee_id INTEGER REFERENCES employees(id) NOT NULL,
            amount FLOAT NOT NULL,
            date DATE NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS cep VARCHAR(9)",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS payment_entries TEXT",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS discount FLOAT DEFAULT 0",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS discount_type VARCHAR(8)",
        """CREATE TABLE IF NOT EXISTS coupons (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) NOT NULL,
            code VARCHAR(32) NOT NULL,
            type VARCHAR(8) NOT NULL,
            amount FLOAT NOT NULL,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
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
    from app.routes.vale import vale_bp
    from app.routes.despacho import despacho_bp
    from app.routes.config import config_bp
    from app.routes.dre import dre_bp

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
    app.register_blueprint(vale_bp)
    app.register_blueprint(despacho_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(dre_bp)

    @app.context_processor
    def inject_nav_badges():
        from flask_login import current_user
        badges = {'entregas_pendentes': 0, 'entregas_retorno': 0}
        try:
            if current_user.is_authenticated:
                from app.models.sale import Sale
                tid = current_user.tenant_id
                base = Sale.query.filter_by(tenant_id=tid, status='confirmed', delivery_mode='entrega')
                badges['entregas_pendentes'] = base.filter(Sale.dispatched_at == None).count()
                badges['entregas_retorno']   = base.filter(Sale.dispatched_at != None, Sale.delivered_at == None).count()
        except Exception:
            pass
        return badges

    with app.app_context():
        app.logger.warning(f"[DB] vars: VENDIX={bool(os.environ.get('VENDIX_DB_URL'))} PUB={bool(os.environ.get('DATABASE_PUBLIC_URL'))} DB={bool(os.environ.get('DATABASE_URL'))}")
        app.logger.warning(f"[DB] Config URI = {app.config['SQLALCHEMY_DATABASE_URI'][:40]}...")
        from app.models.cash_withdrawal import CashWithdrawal  # noqa: F401
        from app.models.expense import Expense  # noqa: F401
        from app.models.combo import ComboItem  # noqa: F401
        from app.models.coupon import Coupon  # noqa: F401
        db.create_all()
        _run_migrations(db)
        from app.seed import seed_master
        seed_master()

    return app
