from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User
from app.models.tenant import Tenant

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            # Verifica se o tenant está ativo (exceto master)
            if not user.is_master:
                tenant = Tenant.query.get(user.tenant_id)
                if not tenant or not tenant.is_active:
                    flash('Sua assinatura está suspensa. Entre em contato com o suporte.', 'danger')
                    return render_template('auth/login.html')
            login_user(user)
            if user.is_master:
                return redirect(url_for('master.dashboard'))
            return redirect(url_for('dashboard.index'))
        flash('E-mail ou senha incorretos.', 'danger')
    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
