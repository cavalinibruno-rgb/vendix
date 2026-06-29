from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User, EmployeeLoginProxy
from app.models.tenant import Tenant
from app.models.vale import Employee
from app.models.password_reset import PasswordResetToken
from app import limiter, db
import os, requests as _requests

auth_bp = Blueprint('auth', __name__)


def _enviar_email_reset(destinatario, link):
    """Envia e-mail de recuperação de senha via Resend API."""
    api_key = os.environ.get('RESEND_API_KEY', '')
    if not api_key:
        current_app.logger.warning('[reset] RESEND_API_KEY não configurada — e-mail não enviado.')
        return

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;">
      <h2 style="color:#c9a84c;">Redefinição de senha</h2>
      <p>Recebemos uma solicitação para redefinir a senha da sua conta Vendix.</p>
      <p>Clique no botão abaixo para criar uma nova senha. O link é válido por <strong>1 hora</strong>.</p>
      <p style="text-align:center;margin:32px 0;">
        <a href="{link}" style="background:#c9a84c;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:bold;">
          Redefinir minha senha
        </a>
      </p>
      <p style="color:#888;font-size:13px;">Se você não solicitou a redefinição, ignore este e-mail. Sua senha permanece a mesma.</p>
      <p style="color:#bbb;font-size:12px;">Vendix — Sistema de Vendas</p>
    </div>
    """

    try:
        resp = _requests.post(
            'https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'from':    'Vendix <onboarding@resend.dev>',
                'to':      [destinatario],
                'subject': 'Redefinição de senha — Vendix',
                'html':    html,
            },
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            current_app.logger.error(f'[reset] Resend erro {resp.status_code}: {resp.text}')
    except Exception as e:
        current_app.logger.error(f'[reset] Falha ao enviar e-mail: {e}')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 30 per hour", methods=["POST"])
def login():
    if request.method == 'POST':
        login_input = request.form.get('email', '').strip()
        password    = request.form.get('password', '')
        remember    = 'remember' in request.form

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


@auth_bp.route('/esqueci-senha', methods=['GET', 'POST'])
@limiter.limit("5 per minute; 10 per hour", methods=["POST"])
def esqueci_senha():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user  = User.query.filter_by(email=email).first()
        # Resposta genérica sempre para evitar enumeração de e-mails
        if user:
            rt   = PasswordResetToken.criar(user.id)
            db.session.commit()
            base = os.environ.get('APP_BASE_URL', 'https://vendixapp.com.br')
            link = f"{base}/redefinir-senha/{rt.token}"
            _enviar_email_reset(user.email, link)
        flash('Se este e-mail estiver cadastrado, você receberá um link em instantes.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/esqueci_senha.html')


@auth_bp.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    rt = PasswordResetToken.query.filter_by(token=token).first()
    if not rt or not rt.valido:
        flash('Link inválido ou expirado. Solicite um novo.', 'danger')
        return redirect(url_for('auth.esqueci_senha'))

    if request.method == 'POST':
        nova = request.form.get('senha', '').strip()
        conf = request.form.get('confirmacao', '').strip()
        if len(nova) < 8:
            flash('A senha deve ter pelo menos 8 caracteres.', 'danger')
            return render_template('auth/redefinir_senha.html', token=token)
        if nova != conf:
            flash('As senhas não coincidem.', 'danger')
            return render_template('auth/redefinir_senha.html', token=token)

        rt.user.set_password(nova)
        rt.used = True
        db.session.commit()
        flash('Senha redefinida com sucesso! Faça login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/redefinir_senha.html', token=token)


@auth_bp.route('/api/session-status')
def session_status():
    from flask import jsonify
    if not current_user.is_authenticated:
        return jsonify({'active': False, 'reason': 'unauthenticated'})
    if current_user.is_master:
        return jsonify({'active': True})
    tenant = current_user.tenant
    if not tenant or not tenant.is_active:
        return jsonify({'active': False, 'reason': 'expired'})
    return jsonify({'active': True})
