from flask import Blueprint, render_template, request, redirect, url_for, jsonify, current_app
from app import db
from app.models.pending_registration import PendingRegistration
from app.models.tenant import Tenant
from app.models.user import User
from datetime import datetime, timedelta
import os, re, unicodedata

register_bp = Blueprint('register', __name__, url_prefix='/assinar')

# Mensal: R$129,90/mês sem fidelidade
# Anual:  R$99,90/mês com fidelidade de 12 meses
PLANOS = {
    'mensal': {
        'nome': 'Vendix Mensal',
        'valor_mensal': 129.90,
        'frequencia': 1,
        'dias': 30,
        'tipo': 'assinatura',   # cobrança recorrente via preapproval
    },
    'anual': {
        'nome': 'Vendix Anual',
        'valor_total': 1198.80,
        'dias': 365,
        'tipo': 'avista',       # pagamento único via Checkout Pro
    },
}


def _make_slug(store_name):
    base = unicodedata.normalize('NFKD', store_name).encode('ascii', 'ignore').decode()
    base = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-') or 'loja'
    slug, n = base, 1
    while Tenant.query.filter_by(slug=slug).first():
        slug = f'{base}-{n}'; n += 1
    return slug


def _criar_conta(pending, preapproval_id=None):
    if pending.status == 'created':
        return
    slug = _make_slug(pending.store_name)
    dias = PLANOS.get(pending.plano, PLANOS['mensal'])['dias']
    tenant = Tenant(
        slug=slug,
        store_name=pending.store_name,
        email=pending.email,
        plan=pending.plano,
        status='active',
        expires_at=datetime.now() + timedelta(days=dias),
        preapproval_id=preapproval_id,
        profile_complete=False,
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


def _renovar_conta(pending):
    """Renova a data de expiração quando um pagamento recorrente é confirmado."""
    tenant = Tenant.query.filter_by(email=pending.email).first()
    if not tenant:
        return
    dias = PLANOS.get(pending.plano, PLANOS['mensal'])['dias']
    agora = datetime.now()
    base = tenant.expires_at if tenant.expires_at and tenant.expires_at > agora else agora
    tenant.expires_at = base + timedelta(days=dias)
    tenant.status = 'active'
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

    access_token = os.environ.get('MP_ACCESS_TOKEN', '')
    if not access_token:
        return jsonify({'error': 'Pagamento indisponível no momento.'}), 500

    from werkzeug.security import generate_password_hash
    pending = PendingRegistration(
        store_name    = store_name,
        email         = email,
        password_hash = generate_password_hash(senha),
        plano         = plano,
    )
    db.session.add(pending)
    db.session.flush()

    import mercadopago
    sdk = mercadopago.SDK(access_token)
    plano_info = PLANOS[plano]
    base_url = os.environ.get('APP_BASE_URL', 'https://vendixapp.com.br')

    if plano_info['tipo'] == 'assinatura':
        # Mensal: assinatura recorrente via Preapproval
        payload = {
            'reason': plano_info['nome'],
            'external_reference': str(pending.id),
            'payer_email': email,
            'auto_recurring': {
                'frequency': plano_info['frequencia'],
                'frequency_type': 'months',
                'transaction_amount': plano_info['valor_mensal'],
                'currency_id': 'BRL',
            },
            'back_url': f'{base_url}/assinar/sucesso',
            'status': 'pending',
            'notification_url': f'{base_url}/assinar/webhook',
        }
        result = sdk.preapproval().create(payload)
        if result['status'] not in (200, 201):
            db.session.rollback()
            current_app.logger.error(f'[MP preapproval] {result}')
            return jsonify({'error': 'Erro ao criar assinatura. Tente novamente.'}), 500
        pending.preference_id = result['response']['id']
        db.session.commit()
        return jsonify({'redirect': result['response']['init_point'], 'pending_id': pending.id})

    else:
        # Anual: pagamento único via Checkout Pro
        payload = {
            'items': [{
                'title': plano_info['nome'] + ' — Vendix',
                'quantity': 1,
                'unit_price': plano_info['valor_total'],
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
            'payment_methods': {
                'installments': 12,
                'default_installments': 12,
            },
        }
        result = sdk.preference().create(payload)
        if result['status'] not in (200, 201):
            db.session.rollback()
            current_app.logger.error(f'[MP preference] {result}')
            return jsonify({'error': 'Erro ao criar pagamento. Tente novamente.'}), 500
        pending.preference_id = result['response']['id']
        db.session.commit()
        return jsonify({'redirect': result['response']['init_point'], 'pending_id': pending.id})


@register_bp.route('/webhook', methods=['POST'])
def webhook():
    data  = request.get_json(silent=True) or {}
    topic = data.get('type') or request.args.get('topic', '')
    resource_id = (data.get('data') or {}).get('id') or request.args.get('id')

    if not resource_id:
        return '', 200

    access_token = os.environ.get('MP_ACCESS_TOKEN', '')
    if not access_token:
        return '', 200

    try:
        import mercadopago
        sdk = mercadopago.SDK(access_token)

        if topic == 'preapproval':
            # Assinatura mensal autorizada → cria conta (novo cliente)
            resp = sdk.preapproval().get(resource_id)
            if resp['status'] != 200:
                return '', 200
            pa = resp['response']
            if pa.get('status') != 'authorized':
                return '', 200
            ext_ref = pa.get('external_reference')
            if not ext_ref:
                return '', 200
            pending = PendingRegistration.query.get(int(ext_ref))
            if pending and pending.status == 'pending':
                pending.payment_id = str(resource_id)
                _criar_conta(pending, preapproval_id=str(resource_id))

        elif topic == 'payment':
            resp = sdk.payment().get(resource_id)
            if resp['status'] != 200:
                return '', 200
            p = resp['response']
            if p.get('status') != 'approved':
                return '', 200
            ext_ref = p.get('external_reference') or ''
            if not ext_ref:
                return '', 200

            # Upgrade de mensal para anual (cliente já existente)
            if ext_ref.startswith('upgrade_'):
                try:
                    tenant_id = int(ext_ref.split('_')[1])
                    tenant = Tenant.query.get(tenant_id)
                    if tenant and tenant.plan != 'anual':
                        tenant.plan = 'anual'
                        tenant.status = 'active'
                        base = tenant.expires_at if tenant.expires_at and tenant.expires_at > datetime.now() else datetime.now()
                        tenant.expires_at = base + timedelta(days=365)
                        tenant.preapproval_id = None
                        db.session.commit()
                except Exception as e:
                    current_app.logger.error(f'[webhook upgrade] {e}')
                return '', 200

            try:
                pending = PendingRegistration.query.get(int(ext_ref))
            except Exception:
                pending = None
            if not pending:
                return '', 200
            if pending.status == 'pending':
                # Pagamento único (anual) → cria conta
                pending.payment_id = str(resource_id)
                _criar_conta(pending)
            elif pending.status == 'created':
                # Cobrança recorrente (mensal) → renova
                _renovar_conta(pending)

    except Exception as e:
        current_app.logger.error(f'[webhook MP] {e}')

    return '', 200


@register_bp.route('/sucesso')
def sucesso():
    preapproval_id = request.args.get('preapproval_id') or request.args.get('collection_id')
    ext_ref        = request.args.get('external_reference')
    status         = request.args.get('status', '')
    pending        = None
    tenant         = None

    if ext_ref:
        try:
            pending = PendingRegistration.query.get(int(ext_ref))
        except Exception:
            pass

    # Tenta criar conta caso o webhook ainda não tenha chegado
    if pending and pending.status == 'pending':
        access_token = os.environ.get('MP_ACCESS_TOKEN', '')
        if access_token and preapproval_id:
            try:
                import mercadopago
                sdk = mercadopago.SDK(access_token)
                resp = sdk.preapproval().get(preapproval_id)
                if resp['status'] == 200 and resp['response'].get('status') == 'authorized':
                    pending.payment_id = preapproval_id
                    _criar_conta(pending)
            except Exception as e:
                current_app.logger.error(f'[sucesso] {e}')
                db.session.rollback()

    if pending and pending.status == 'created':
        tenant = Tenant.query.filter_by(email=pending.email).first()

    return render_template('register/sucesso.html', pending=pending, tenant=tenant, status=status)


@register_bp.route('/status/<int:pending_id>')
def status(pending_id):
    pending = PendingRegistration.query.get_or_404(pending_id)
    return jsonify({'status': pending.status, 'email': pending.email if pending.status == 'created' else None})


@register_bp.route('/falha')
def falha():
    return render_template('register/sucesso.html', pending=None, tenant=None, status='failure')


@register_bp.route('/pendente')
def pendente():
    return render_template('register/sucesso.html', pending=None, tenant=None, status='pending')
