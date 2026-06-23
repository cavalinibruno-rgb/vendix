from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from werkzeug.security import generate_password_hash
from app.models.coupon import Coupon
import requests as _req, json as _json

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

@config_bp.route('/localizacao', methods=['POST'])
@login_required
def salvar_localizacao():
    tenant = current_user.tenant
    cfg = tenant.get_settings()
    cfg['loja_lat']      = request.form.get('loja_lat', '').strip()
    cfg['loja_lng']      = request.form.get('loja_lng', '').strip()
    cfg['loja_endereco'] = request.form.get('loja_endereco', '').strip()
    # Zonas: lista de {max_km, fee}
    zonas = []
    maxs = request.form.getlist('zona_max_km')
    fees = request.form.getlist('zona_fee')
    for m, f in zip(maxs, fees):
        try:
            zonas.append({'max_km': float(m.replace(',','.')), 'fee': float(f.replace(',','.'))})
        except ValueError:
            pass
    zonas.sort(key=lambda z: z['max_km'])
    cfg['zonas_entrega'] = zonas
    tenant.save_settings(cfg)
    db.session.commit()
    flash('Localização e zonas de entrega salvas.', 'success')
    return redirect(url_for('config.index') + '#localizacao')


@config_bp.route('/geocodificar')
@login_required
def geocodificar():
    cep    = request.args.get('cep', '').strip().replace('-', '')
    numero = request.args.get('numero', '').strip()
    if not cep:
        return jsonify({'error': 'CEP não informado.'})
    try:
        via = _req.get(f'https://viacep.com.br/ws/{cep}/json/', timeout=5).json()
        if via.get('erro'):
            return jsonify({'error': 'CEP não encontrado.'})
        logradouro = via.get('logradouro', '')
        bairro     = via.get('bairro', '')
        cidade     = via.get('localidade', '')
        uf         = via.get('uf', '')
        headers = {'User-Agent': 'Vendix/1.0'}
        # Tenta do mais específico ao mais amplo
        queries = [
            f'{logradouro}, {numero}, {cidade}, {uf}, Brasil',
            f'{logradouro}, {cidade}, {uf}, Brasil',
            f'{bairro}, {cidade}, {uf}, Brasil',
            f'{cidade}, {uf}, Brasil',
        ]
        for q in queries:
            if not q.replace(',','').replace(' ',''):
                continue
            nom = _req.get(
                'https://nominatim.openstreetmap.org/search',
                params={'q': q, 'format': 'json', 'limit': 1, 'countrycodes': 'br'},
                headers=headers, timeout=8
            ).json()
            if nom:
                endereco = f'{logradouro}, {numero}, {bairro}, {cidade} - {uf}' if logradouro else q
                return jsonify({'lat': nom[0]['lat'], 'lng': nom[0]['lon'], 'endereco': endereco})
        return jsonify({'error': 'Endereço não encontrado automaticamente. Use o campo manual abaixo.'})
    except Exception as e:
        return jsonify({'error': f'Erro ao buscar: {str(e)}'})


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

    if current_user.is_employee:
        from app.models.vale import Employee
        emp = Employee.query.get(current_user._emp.id)
        emp.set_password(nova_senha)
    else:
        current_user.password_hash = generate_password_hash(nova_senha)
    db.session.commit()
    flash('Senha alterada com sucesso!', 'success')
    return redirect(url_for('config.index'))
