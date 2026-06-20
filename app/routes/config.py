from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db

config_bp = Blueprint('config', __name__, url_prefix='/configuracoes')

def tid():
    return current_user.tenant_id

@config_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    tenant = current_user.tenant
    cfg = tenant.get_settings()

    if request.method == 'POST':
        cfg['whatsapp_notify'] = 'whatsapp_notify' in request.form
        cfg['whatsapp_msg'] = request.form.get('whatsapp_msg', '').strip()
        tenant.save_settings(cfg)
        db.session.commit()
        flash('Configurações salvas.', 'success')
        return redirect(url_for('config.index'))

    return render_template('config/index.html', cfg=cfg)

@config_bp.route('/dashboard-operador', methods=['POST'])
@login_required
def dashboard_operador():
    tenant = current_user.tenant
    cfg = tenant.get_settings()
    cfg['dashboard_operador_restrito'] = 'dashboard_operador_restrito' in request.form
    tenant.save_settings(cfg)
    db.session.commit()
    flash('Configuração salva.', 'success')
    return redirect(url_for('config.index'))
