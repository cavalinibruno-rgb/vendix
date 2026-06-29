from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
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
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri="memory://")
csrf = CSRFProtect()

LOJA_DOMAIN_SUFFIX = '.vendixapp.com.br'
APP_VERSION = '1.0.3'


class LojaSubdomainMiddleware:
    """Reescreve <slug>.vendixapp.com.br/<path> → /loja/<slug>/<path> internamente."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        host = environ.get('HTTP_HOST', '').split(':')[0].lower()
        if (host.endswith(LOJA_DOMAIN_SUFFIX)
                and host not in ('vendixapp.com.br', 'www.vendixapp.com.br')):
            slug   = host[:-len(LOJA_DOMAIN_SUFFIX)]
            path   = environ.get('PATH_INFO', '/')
            prefix = f'/loja/{slug}'
            if not path.startswith(prefix):
                environ['PATH_INFO'] = (prefix + path).rstrip('/') or prefix
        return self.app(environ, start_response)


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
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS sale_price_card FLOAT DEFAULT 0",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS cash_register_id INTEGER REFERENCES cash_registers(id)",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS payment_method VARCHAR(16) DEFAULT 'dinheiro'",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS operator_name VARCHAR(128)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS sale_price_event FLOAT DEFAULT 0",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS event_mode BOOLEAN DEFAULT FALSE",
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
        """CREATE TABLE IF NOT EXISTS customer_addresses (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) NOT NULL,
            customer_id INTEGER REFERENCES customers(id) NOT NULL,
            label VARCHAR(64),
            address VARCHAR(256),
            neighborhood_id INTEGER REFERENCES neighborhoods(id),
            delivery_fee FLOAT DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        "ALTER TABLE coupons ADD COLUMN IF NOT EXISTS starts_at TIMESTAMP",
        "ALTER TABLE coupons ADD COLUMN IF NOT EXISTS ends_at TIMESTAMP",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_data BYTEA",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_mime VARCHAR(32)",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS preapproval_id VARCHAR(128)",
        """CREATE TABLE IF NOT EXISTS app_releases (
            id SERIAL PRIMARY KEY,
            version VARCHAR(32) NOT NULL,
            description TEXT,
            filename VARCHAR(256) NOT NULL,
            file_data BYTEA NOT NULL,
            file_size INTEGER NOT NULL,
            platform VARCHAR(16) DEFAULT 'android',
            uploaded_at TIMESTAMP DEFAULT NOW()
        )""",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS profile_complete BOOLEAN DEFAULT TRUE",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS street VARCHAR(256)",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS number VARCHAR(16)",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS neighborhood VARCHAR(128)",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS city VARCHAR(128)",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS state VARCHAR(2)",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS cep VARCHAR(9)",
        """CREATE TABLE IF NOT EXISTS pending_registrations (
            id SERIAL PRIMARY KEY,
            store_name VARCHAR(128) NOT NULL,
            email VARCHAR(128) NOT NULL,
            password_hash VARCHAR(256) NOT NULL,
            plano VARCHAR(16) NOT NULL,
            preference_id VARCHAR(128),
            payment_id VARCHAR(128),
            status VARCHAR(16) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        # Índices de performance
        "DROP INDEX IF EXISTS idx_sales_tenant_id",
        "DROP INDEX IF EXISTS idx_sales_tenant_status",
        "CREATE INDEX IF NOT EXISTS idx_sales_tenant_created ON sales(tenant_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_sales_tenant_created_status ON sales(tenant_id, created_at DESC, status)",
        "CREATE INDEX IF NOT EXISTS idx_pedidos_tenant_status ON pedidos_online(tenant_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_pedidos_tenant_created ON pedidos_online(tenant_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_products_tenant_id ON products(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_sale_items_sale_id ON sale_items(sale_id)",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS employee_id INTEGER REFERENCES employees(id)",
        "ALTER TABLE vales ADD COLUMN IF NOT EXISTS sale_id INTEGER REFERENCES sales(id)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS address_number VARCHAR(16)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS address_ref VARCHAR(256)",
        "ALTER TABLE sales ALTER COLUMN payment_method TYPE VARCHAR(32)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS image_url VARCHAR(512)",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_url VARCHAR(512)",
        "ALTER TABLE app_releases ADD COLUMN IF NOT EXISTS file_url VARCHAR(512)",
        "ALTER TABLE app_releases ALTER COLUMN file_data DROP NOT NULL",
        "ALTER TABLE app_releases ADD COLUMN IF NOT EXISTS file_sha512 VARCHAR(128)",
        "ALTER TABLE pedidos_online ADD COLUMN IF NOT EXISTS sale_id INTEGER REFERENCES sales(id)",
        "ALTER TABLE pedidos_online ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP",
        "ALTER TABLE pedidos_online ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP",
        "ALTER TABLE pedidos_online ADD COLUMN IF NOT EXISTS reject_reason TEXT",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS pack_parent_id INTEGER REFERENCES products(id)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS pack_qty INTEGER",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS sale_price_cold FLOAT DEFAULT 0",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS sale_number INTEGER",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS sale_price_cold_card FLOAT DEFAULT 0",
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
    app.config['MAX_CONTENT_LENGTH'] = 150 * 1024 * 1024  # 150 MB

    from datetime import timedelta
    app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Faça login para acessar.'
    limiter.init_app(app)
    csrf.init_app(app)

    from app.routes.main import main_bp
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
    from app.routes.loja import loja_bp
    from app.routes.pedidos_online import pedidos_online_bp
    from app.routes.register import register_bp
    from app.routes.assinatura import assinatura_bp
    from app.routes.completar_cadastro import completar_cadastro_bp
    from app.routes.download import download_bp

    app.register_blueprint(main_bp)
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
    app.register_blueprint(loja_bp)
    app.register_blueprint(pedidos_online_bp)
    app.register_blueprint(register_bp)
    app.register_blueprint(assinatura_bp)
    app.register_blueprint(completar_cadastro_bp)
    app.register_blueprint(download_bp)

    @app.before_request
    def verificar_assinatura_ativa():
        from flask import request as req, redirect, url_for
        from flask_login import current_user, logout_user
        rotas_liberadas = {'auth.login', 'auth.logout', 'static', 'main.index',
                           'register.form', 'register.checkout', 'register.webhook',
                           'register.sucesso', 'register.status', 'register.falha',
                           'register.pendente', 'download.pagina', 'download.arquivo',
                           'download.latest_yml', 'download.update_file'}
        if req.endpoint in rotas_liberadas:
            return
        if not current_user.is_authenticated or current_user.is_master:
            return
        tenant = current_user.tenant
        if tenant and not tenant.is_active:
            logout_user()
            from flask import flash
            flash('Sua assinatura venceu. Renove para continuar acessando.', 'warning')
            return redirect(url_for('auth.login'))

    @app.before_request
    def verificar_perfil_completo():
        from flask import request as req, redirect, url_for
        from flask_login import current_user
        rotas_liberadas = {'completar_cadastro.index', 'auth.logout', 'auth.login', 'static'}
        if req.endpoint in rotas_liberadas:
            return
        if not current_user.is_authenticated:
            return
        if current_user.is_master or current_user.is_employee:
            return
        tenant = current_user.tenant
        if tenant and not tenant.profile_complete:
            return redirect(url_for('completar_cadastro.index'))

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        return response

    @app.errorhandler(429)
    def rate_limit_exceeded(e):
        from flask import request, jsonify
        if request.is_json or request.path.startswith('/loja/'):
            return jsonify(erro='Muitas requisições. Tente novamente em instantes.'), 429
        from flask import render_template
        return render_template('errors/429.html'), 429

    @app.context_processor
    def inject_app_version():
        return {'app_version': APP_VERSION}

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
        from app.models.customer_address import CustomerAddress  # noqa: F401
        from app.models.pedido_online import PedidoOnline  # noqa: F401
        from app.models.pending_registration import PendingRegistration  # noqa: F401
        from app.models.app_release import AppRelease  # noqa: F401
        from app.models.sale_archive import SaleArchive  # noqa: F401
        db.create_all()
        _run_migrations(db)
        from app.seed import seed_master
        seed_master()

    app.wsgi_app = LojaSubdomainMiddleware(app.wsgi_app)
    return app
