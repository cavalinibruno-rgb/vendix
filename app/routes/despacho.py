from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.models.sale import Sale
from app.models.motoboy import Motoboy

despacho_bp = Blueprint('despacho', __name__, url_prefix='/despacho')

def tid():
    return current_user.tenant_id

@despacho_bp.route('/')
@login_required
def index():
    pendentes = (Sale.query
                 .filter_by(tenant_id=tid(), status='confirmed', delivery_mode='entrega')
                 .filter(Sale.dispatched_at == None)
                 .order_by(Sale.created_at.asc()).all())

    despachados = (Sale.query
                   .filter_by(tenant_id=tid(), status='confirmed', delivery_mode='entrega')
                   .filter(Sale.dispatched_at != None)
                   .order_by(Sale.dispatched_at.desc()).limit(20).all())

    motoboys = Motoboy.query.filter_by(tenant_id=tid(), active=True).order_by(Motoboy.name).all()

    tenant = current_user.tenant
    cfg = tenant.get_settings()

    return render_template('despacho/index.html',
        pendentes=pendentes, despachados=despachados,
        motoboys=motoboys, cfg=cfg)

@despacho_bp.route('/<int:sale_id>/despachar', methods=['POST'])
@login_required
def despachar(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    motoboy_id = request.form.get('motoboy_id', type=int)

    motoboy = Motoboy.query.filter_by(id=motoboy_id, tenant_id=tid()).first() if motoboy_id else None
    sale.dispatched_at  = datetime.now()
    sale.motoboy_id     = motoboy.id if motoboy else None
    sale.motoboy_name   = motoboy.name if motoboy else None
    db.session.commit()

    cfg = current_user.tenant.get_settings()
    wa_url = None
    if cfg.get('whatsapp_notify') and sale.customer and sale.customer.phone:
        phone = ''.join(filter(str.isdigit, sale.customer.phone))
        if not phone.startswith('55'):
            phone = '55' + phone
        msg_tpl = cfg.get('whatsapp_msg') or 'Olá {cliente}! Seu pedido saiu para entrega com o motoboy {motoboy}. Em breve chegará até você!'
        msg = (msg_tpl
               .replace('{cliente}', sale.customer.name)
               .replace('{motoboy}', motoboy.name if motoboy else 'nosso entregador'))
        import urllib.parse
        wa_url = f'whatsapp://send?phone={phone}&text={urllib.parse.quote(msg)}'

    return jsonify({'ok': True, 'wa_url': wa_url, 'sale_id': sale.id})
