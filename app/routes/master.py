from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models.tenant import Tenant
from app.models.user import User
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from functools import wraps

master_bp = Blueprint('master', __name__, url_prefix='/master')

def master_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_master:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

@master_bp.route('/')
@login_required
@master_required
def dashboard():
    tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
    return render_template('master/dashboard.html', tenants=tenants)

@master_bp.route('/tenant/novo', methods=['GET', 'POST'])
@login_required
@master_required
def tenant_novo():
    if request.method == 'POST':
        store_name = request.form.get('store_name', '').strip()
        email      = request.form.get('email', '').strip().lower()
        phone      = request.form.get('phone', '').strip()
        password   = request.form.get('password', '').strip()
        dias       = int(request.form.get('dias', 30))
        slug       = store_name.lower().replace(' ', '-')

        if Tenant.query.filter_by(email=email).first():
            flash('E-mail já cadastrado.', 'danger')
            return render_template('master/tenant_form.html')

        tenant = Tenant(
            slug=slug,
            store_name=store_name,
            email=email,
            phone=phone,
            status='active',
            expires_at=datetime.utcnow() + timedelta(days=dias)
        )
        db.session.add(tenant)
        db.session.flush()

        user = User(
            tenant_id=tenant.id,
            username='admin',
            email=email,
            display_name=store_name,
            role='admin'
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f'Loja "{store_name}" criada com sucesso!', 'success')
        return redirect(url_for('master.dashboard'))

    return render_template('master/tenant_form.html')

@master_bp.route('/tenant/<int:tenant_id>/suspender')
@login_required
@master_required
def tenant_suspender(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    tenant.status = 'suspended'
    db.session.commit()
    flash(f'Loja "{tenant.store_name}" suspensa.', 'warning')
    return redirect(url_for('master.dashboard'))

@master_bp.route('/tenant/<int:tenant_id>/ativar', methods=['POST'])
@login_required
@master_required
def tenant_ativar(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    dias = int(request.form.get('dias', 30))
    tenant.status = 'active'
    tenant.expires_at = datetime.utcnow() + timedelta(days=dias)
    db.session.commit()
    flash(f'Loja "{tenant.store_name}" reativada por {dias} dias.', 'success')
    return redirect(url_for('master.dashboard'))
