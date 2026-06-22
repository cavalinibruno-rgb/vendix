from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from werkzeug.security import generate_password_hash
from app.models.coupon import Coupon

config_bp = Blueprint('config', __name__, url_prefix='/configuracoes')

def tid():
    return current_user.tenant_id

@config_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    tenant = current_user.tenant
    cfg = tenant.get_settings()
    coupons = Coupon.query.filter_by(tenant_id=tid()).order_by(Coupon.created_at.desc()).all()

    if request.method == 'POST':
        cfg['whatsapp_notify'] = 'whatsapp_notify' in request.form
        cfg['whatsapp_msg'] = request.form.get('whatsapp_msg', '').strip()
        tenant.save_settings(cfg)
        db.session.commit()
        flash('Configurações salvas.', 'success')
        return redirect(url_for('config.index'))

    return render_template('config/index.html', cfg=cfg, coupons=coupons, tenant=tenant)

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

@config_bp.route('/cupons/criar', methods=['POST'])
@login_required
def criar_cupom():
    code   = request.form.get('code', '').strip().upper()
    ctype  = request.form.get('type', 'percent')
    amount = request.form.get('amount', '0').replace(',', '.').strip()
    try:
        amount = float(amount)
    except ValueError:
        flash('Valor inválido.', 'danger')
        return redirect(url_for('config.index') + '#cupons')
    if not code:
        flash('Informe o código do cupom.', 'danger')
        return redirect(url_for('config.index') + '#cupons')
    if Coupon.query.filter_by(tenant_id=tid(), code=code).first():
        flash(f'Cupom "{code}" já existe.', 'danger')
        return redirect(url_for('config.index') + '#cupons')
    db.session.add(Coupon(tenant_id=tid(), code=code, coupon_type=ctype, amount=amount))
    db.session.commit()
    flash(f'Cupom "{code}" criado com sucesso.', 'success')
    return redirect(url_for('config.index') + '#cupons')

@config_bp.route('/cupons/<int:coupon_id>/toggle', methods=['POST'])
@login_required
def toggle_cupom(coupon_id):
    c = Coupon.query.filter_by(id=coupon_id, tenant_id=tid()).first_or_404()
    c.active = not c.active
    db.session.commit()
    flash(f'Cupom "{c.code}" {"ativado" if c.active else "desativado"}.', 'success')
    return redirect(url_for('config.index') + '#cupons')

@config_bp.route('/cupons/<int:coupon_id>/excluir', methods=['POST'])
@login_required
def excluir_cupom(coupon_id):
    c = Coupon.query.filter_by(id=coupon_id, tenant_id=tid()).first_or_404()
    db.session.delete(c)
    db.session.commit()
    flash(f'Cupom "{c.code}" excluído.', 'success')
    return redirect(url_for('config.index') + '#cupons')

@config_bp.route('/alterar-senha', methods=['POST'])
@login_required
def alterar_senha():
    senha_atual  = request.form.get('senha_atual', '')
    nova_senha   = request.form.get('nova_senha', '')
    confirmar    = request.form.get('confirmar_senha', '')

    if not current_user.check_password(senha_atual):
        flash('Senha atual incorreta.', 'danger')
        return redirect(url_for('config.index') + '#seguranca')

    if len(nova_senha) < 4:
        flash('A nova senha deve ter pelo menos 4 caracteres.', 'danger')
        return redirect(url_for('config.index') + '#seguranca')

    if nova_senha != confirmar:
        flash('As senhas não coincidem.', 'danger')
        return redirect(url_for('config.index') + '#seguranca')

    current_user.password_hash = generate_password_hash(nova_senha)
    db.session.commit()
    flash('Senha alterada com sucesso!', 'success')
    return redirect(url_for('config.index'))
