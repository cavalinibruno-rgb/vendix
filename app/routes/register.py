from flask import Blueprint, render_template, request, redirect, url_for, jsonify, current_app
from app import db
from app.models.pending_registration import PendingRegistration
from app.models.tenant import Tenant
from app.models.user import User
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import os, re, unicodedata, hmac, hashlib, json

register_bp = Blueprint('register', __name__, url_prefix='/assinar')

PLANOS = {
    'mensal': {'nome': 'Plano Mensal', 'preco': 129.90, 'dias': 30},
    'anual':  {'nome': 'Plano Anual',  'preco': 1198.80, 'dias': 365},
}


def _make_slug(store_name):
    base = unicodedata.normalize('NFKD', store_name).encode('ascii', 'ignore').decode()
    base = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-') or 'loja'
    slug, n = base, 1
    while Tenant.query.filter_by(slug=slug).first():
        slug = f'{base}-{n}'; n += 1
    return slug


def _criar_conta(pending):
    if pending.status == 'created':
        return
    slug = _make_slug(pending.store_name)
    plano_info = PLANOS.get(pending.plano, PLANOS['mensal'])
    tenant = Tenant(
        slug=slug,
        store_name=pending.store_name,
        email=pending.email,
        plan=pending.plano,
        status='active',
        expires_at=datetime.now() + timedelta(days=plano_info['dias']),
    )
    db.session.add(tenant)
    db.session.flush()
    user = User(
        tenant_id=tenant.id,
        username='admin',
        email=pending.email,
        display_name=pending.store_name,
        role='admin',
        password_hash=pending.password_hash,
    )
    db.session.add(user)
    pending.status = 'created'
    db.session.commit()


@register_bp.route('/', methods=['GET'])
def form():
    plano = request.args.get('plano', 'mensal')
    return render_template('register/assinar.html', plano=plano)


@register_bp.route('/checkout', methods=['POST'])
def checkout():
    store_name = request.form.get('store_name', '').strip()
    email      = request.form.get('email', '').strip().lower()
    senha      = request.form.get('senha', '').strip()
    plano      = request.form.get('plano', 'mensal')

    if not store_name or not email or len(senha) < 6:
        return jsonify({'error': 'Preencha todos os campos. Senha mínima: 6 caracteres.'}), 400
    if plano not in PLANOS:
        return jsonify({'error': 'Plano inválido.'}), 400
    if Tenant.query.filter_by(email=email).first():
        return jsonify({'error': 'E-mail já cadastrado. Acesse o sistema para entrar.'}), 400

    pending = PendingRegistration(
        store_name    = store_name,
        email         = email,
        password_hash = generate_password_hash(senha),
        plano         = plano,
    )
    db.session.add(pending)
    db.session.flush()

    access_token = os.environ.get('MP_ACCESS_TOKEN', '')
    if not access_token:
        db.session.rollback()
        return jsonify({'error': 'Pagamento indisponível no momento.'}), 500

    import mercadopago
    sdk = mercadopago.SDK(access_token)
    plano_info = PLANOS[plano]
    base_url = os.environ.get('APP_BASE_URL', 'https://vendixapp.com.br')

    preference_data = {
        'items': [{
            'title': plano_info['nome'] + ' — Vendix',
            'quantity': 1,
            'unit_price': plano_info['preco'],
            'currency_id': 'BRL',
        }],
        'payer': {'email': email},
        'back_urls': {
            'success': f'{base_url}/assinar/sucesso',
            'failure': f'{base_url}/assinar/falha',
            'pending': f'{base_url}/assinar/pendente',
        },
        'auto_return': 'approved',
        'external_reference': str(pending.id),
        'notification_url': f'{base_url}/assinar/webhook',
        'statement_descriptor': 'VENDIX',
        'installments': 12 if plano == 'anual' else 1,
    }
    result = sdk.preference().create(preference_data)
    if result['status'] != 201:
        db.session.rollback()
        return jsonify({'error': 'Erro ao criar preferência de pagamento.'}), 500

    pending.preference_id = result['response']['id']
    db.session.commit()

    is_sandbox = 'TEST' in access_token.upper() or access_token.startswith('TEST')
    init_point = result['response']['sandbox_init_point' if is_sandbox else 'init_point']
    return jsonify({'redirect': init_point})


@register_bp.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(silent=True) or {}
    topic = data.get('type') or request.args.get('topic', '')
    resource_id = (data.get('data') or {}).get('id') or request.args.get('id')

    if topic not in ('payment', 'merchant_order'):
        return '', 200

    access_token = os.environ.get('MP_ACCESS_TOKEN', '')
    if not access_token or not resource_id:
        return '', 200

    try:
        import mercadopago
        sdk = mercadopago.SDK(access_token)
        payment = sdk.payment().get(resource_id)
        if payment['status'] != 200:
            return '', 200
        p = payment['response']
        if p.get('status') != 'approved':
            return '', 200
        ext_ref = p.get('external_reference')
        if not ext_ref:
            return '', 200
        pending = PendingRegistration.query.get(int(ext_ref))
        if pending and pending.status == 'pending':
            pending.payment_id = str(resource_id)
            _criar_conta(pending)
    except Exception as e:
        current_app.logger.error(f'[webhook MP] {e}')

    return '', 200


@register_bp.route('/sucesso')
def sucesso():
    payment_id   = request.args.get('payment_id')
    ext_ref      = request.args.get('external_reference')
    status       = request.args.get('status')
    pending      = None
    tenant       = None

    if ext_ref:
        try:
            pending = PendingRegistration.query.get(int(ext_ref))
        except Exception:
            pass

    # Se o webhook ainda não criou a conta, tenta criar agora
    if pending and pending.status == 'pending' and status == 'approved':
        if payment_id:
            pending.payment_id = payment_id
        try:
            _criar_conta(pending)
        except Exception as e:
            current_app.logger.error(f'[sucesso] erro ao criar conta: {e}')
            db.session.rollback()

    if pending and pending.status == 'created':
        tenant = Tenant.query.filter_by(email=pending.email).first()

    return render_template('register/sucesso.html', pending=pending, tenant=tenant, status=status)


@register_bp.route('/falha')
def falha():
    return render_template('register/sucesso.html', pending=None, tenant=None, status='failure')


@register_bp.route('/pendente')
def pendente():
    return render_template('register/sucesso.html', pending=None, tenant=None, status='pending')
