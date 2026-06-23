from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User, EmployeeLoginProxy
from app.models.tenant import Tenant
from app.models.vale import Employee

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_input = request.form.get('email', '').strip()
        password    = request.form.get('password', '')
        remember    = 'remember' in request.form

        # Tenta login como dono/admin (por e-mail)
        user = User.query.filter_by(email=login_input.lower()).first()
        if user and user.check_password(password):
            if not user.is_master:
                tenant = Tenant.query.get(user.tenant_id)
                if not tenant or not tenant.is_active:
                    flash('Sua assinatura está suspensa. Entre em contato com o suporte.', 'danger')
                    return render_template('auth/login.html')
            login_user(user, remember=remember)
            if user.is_master:
                return redirect(url_for('master.dashboard'))
            return redirect(url_for('dashboard.index'))

        # Tenta login como operador de caixa (por username)
        emp = Employee.query.filter_by(username=login_input).first()
        if emp and emp.check_password(password):
            tenant = Tenant.query.get(emp.tenant_id)
            if not tenant or not tenant.is_active:
                flash('Sua assinatura está suspensa. Entre em contato com o suporte.', 'danger')
                return render_template('auth/login.html')
            proxy = EmployeeLoginProxy(emp)
            login_user(proxy, remember=remember)
            return redirect(url_for('dashboard.index'))

        flash('Usuário ou senha incorretos.', 'danger')
    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
