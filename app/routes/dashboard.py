from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.models.tenant import Tenant

dashboard_bp = Blueprint('dashboard', __name__)

def require_active_tenant(f):
    from functools import wraps
    from flask import redirect, url_for, flash
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.is_master:
            return f(*args, **kwargs)
        tenant = Tenant.query.get(current_user.tenant_id)
        if not tenant or not tenant.is_active:
            flash('Sua assinatura está suspensa.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

@dashboard_bp.route('/')
@login_required
@require_active_tenant
def index():
    tenant = Tenant.query.get(current_user.tenant_id)
    return render_template('dashboard/index.html', tenant=tenant)
