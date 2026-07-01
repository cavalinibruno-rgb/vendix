from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
from flask_login import login_required, current_user
from app import db
from app.models.tenant import Tenant
from datetime import datetime, timedelta
import os

assinatura_bp = Blueprint('assinatura', __name__, url_prefix='/minha-assinatura')


@assinatura_bp.route('/')
@login_required
def index():
    if current_user.is_employee:
        return redirect(url_for('dashboard.index'))
    tenant = current_user.tenant
    aguardando_upgrade = session.pop('upgrade_pending_id', None)
    return render_template('assinatura/index.html', tenant=tenant,
                           aguardando_upgrade=aguardando_upgrade)


@assinatura_bp.route('/cancelar', methods=['POST'])
@login_required
def cancelar():
    if current_user.is_employee:
        return redirect(url_for('dashboard.index'))
    tenant = current_user.tenant

    access_token = os.environ.get('MP_ACCESS_TOKEN', '')
    if access_token and tenant.preapproval_id:
        try:
            import mercadopago
            sdk = mercadopago.SDK(access_token)
            sdk.preapproval().update(tenant.preapproval_id, {'status': 'cancelled'})
        except Exception as e:
            import logging
            logging.error(f'[cancelar assinatura] {e}')

    tenant.preapproval_id = None
    db.session.commit()

    flash('Assinatura cancelada. Seu acesso permanece ativo até o vencimento.', 'warning')
    return redirect(url_for('assinatura.index'))


@assinatura_bp.route('/upgrade-anual', methods=['POST'])
@login_required
def upgrade_anual():
    if current_user.is_employee:
        return jsonify({'error': 'Sem permissão.'}), 403
    tenant = current_user.tenant

    if tenant.plan == 'anual':
        return jsonify({'error': 'Você já está no plano anual.'}), 400

    access_token = os.environ.get('MP_ACCESS_TOKEN', '')
    if not access_token:
        return jsonify({'error': 'Pagamento indisponível no momento.'}), 500

    import mercadopago
    sdk = mercadopago.SDK(access_token)
    base_url = os.environ.get('APP_BASE_URL', 'https://vendixapp.com.br')

    # Cria preferência de pagamento para upgrade anual
    payload = {
        'items': [{
            'title': 'Vendix Anual — Upgrade',
            'quantity': 1,
            'unit_price': 1198.80,
            'currency_id': 'BRL',
        }],
        'payer': {'email': tenant.email},
        'back_urls': {
            'success': f'{base_url}/minha-assinatura/upgrade-sucesso',
            'failure': f'{base_url}/minha-assinatura/',
            'pending': f'{base_url}/minha-assinatura/',
        },
        'auto_return': 'approved',
        'external_reference': f'upgrade_{tenant.id}',
        'notification_url': f'{base_url}/assinar/webhook',
        'statement_descriptor': 'VENDIX',
        'payment_methods': {
            'installments': 12,
            'default_installments': 12,
        },
    }
    result = sdk.preference().create(payload)
    if result['status'] not in (200, 201):
        return jsonify({'error': 'Erro ao criar pagamento. Tente novamente.'}), 500

    # Cancela preapproval mensal antes de redirecionar
    if tenant.preapproval_id:
        try:
            sdk.preapproval().update(tenant.preapproval_id, {'status': 'cancelled'})
            tenant.preapproval_id = None
            db.session.commit()
        except Exception:
            pass

    return jsonify({'redirect': result['response']['init_point']})


@assinatura_bp.route('/upgrade-sucesso')
@login_required
def upgrade_sucesso():
    # O webhook já atualizou o tenant. Só confirma na tela.
    tenant = current_user.tenant
    # Tenta confirmar manualmente se o webhook ainda não chegou
    payment_id = request.args.get('collection_id') or request.args.get('payment_id')
    if payment_id and tenant.plan != 'anual':
        access_token = os.environ.get('MP_ACCESS_TOKEN', '')
        if access_token:
            try:
                import mercadopago
                sdk = mercadopago.SDK(access_token)
                resp = sdk.payment().get(payment_id)
                if resp['status'] == 200 and resp['response'].get('status') == 'approved':
                    tenant.plan = 'anual'
                    tenant.status = 'active'
                    base = tenant.expires_at if tenant.expires_at and tenant.expires_at > datetime.now() else datetime.now()
                    tenant.expires_at = base + timedelta(days=365)
                    tenant.preapproval_id = None
                    db.session.commit()
            except Exception:
                pass
    flash('Upgrade para o plano Anual realizado com sucesso! 🥃', 'success')
    return redirect(url_for('assinatura.index'))


@assinatura_bp.route('/status-upgrade')
@login_required
def status_upgrade():
    tenant = current_user.tenant
    return jsonify({'plan': tenant.plan, 'status': tenant.status})
