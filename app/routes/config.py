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

@config_bp.route('/regime-tributario', methods=['POST'])
@login_required
def regime_tributario():
    tenant = current_user.tenant
    cfg = tenant.get_settings()

    regime = request.form.get('regime_tributario', 'simples')
    cfg['regime_tributario'] = regime

    def fval(name):
        v = request.form.get(name, '0').replace(',', '.').strip() or '0'
        try: return float(v)
        except ValueError: return 0.0

    if regime == 'mei':
        cfg['das_mei'] = fval('das_mei')
    elif regime == 'simples':
        cfg['aliquota_simples'] = fval('aliquota_simples')
    elif regime in ('presumido', 'real'):
        for campo in ('aliq_pis', 'aliq_cofins', 'aliq_iss', 'aliq_icms', 'aliq_irpj', 'aliq_csll'):
            cfg[campo] = fval(campo)

    tenant.save_settings(cfg)
    db.session.commit()
    flash('Regime tributário salvo.', 'success')
    return redirect(url_for('config.index'))

@config_bp.route('/dashboard-operador', methods=['POST'])
@login_required
def dashboard_operador():
    senha = request.form.get('owner_password', '')
    if not current_user.check_password(senha):
        flash('Senha incorreta. Configuração não foi alterada.', 'danger')
        return redirect(url_for('config.index'))
    tenant = current_user.tenant
    cfg = tenant.get_settings()
    cfg['dashboard_operador_restrito'] = 'dashboard_operador_restrito' in request.form
    tenant.save_settings(cfg)
    db.session.commit()
    flash('Configuração salva.', 'success')
    return redirect(url_for('config.index'))
