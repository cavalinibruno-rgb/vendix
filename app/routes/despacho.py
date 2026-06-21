from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.models.sale import Sale
from app.models.motoboy import Motoboy

despacho_bp = Blueprint('entregas', __name__, url_prefix='/entregas')

def tid():
    return current_user.tenant_id

@despacho_bp.route('/')
@login_required
def index():
    base = Sale.query.filter_by(tenant_id=tid(), status='confirmed', delivery_mode='entrega')

    pendentes   = base.filter(Sale.dispatched_at == None).order_by(Sale.created_at.asc()).all()
    em_rota     = (base.filter(Sale.dispatched_at != None, Sale.delivered_at == None)
                       .order_by(Sale.dispatched_at.asc()).all())
    concluidas  = (Sale.query
                       .filter_by(tenant_id=tid(), delivery_mode='entrega')
                       .filter(Sale.delivered_at != None)
                       .order_by(Sale.delivered_at.desc()).limit(20).all())

    motoboys = Motoboy.query.filter_by(tenant_id=tid(), active=True).order_by(Motoboy.name).all()
    cfg = current_user.tenant.get_settings()

    return render_template('despacho/index.html',
        pendentes=pendentes, em_rota=em_rota, concluidas=concluidas,
        motoboys=motoboys, cfg=cfg)

@despacho_bp.route('/<int:sale_id>/despachar', methods=['POST'])
@login_required
def despachar(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    motoboy_id = request.form.get('motoboy_id', type=int)

    motoboy = Motoboy.query.filter_by(id=motoboy_id, tenant_id=tid()).first() if motoboy_id else None
    sale.dispatched_at = datetime.now()
    sale.motoboy_id    = motoboy.id   if motoboy else None
    sale.motoboy_name  = motoboy.name if motoboy else None
    db.session.commit()

    cfg = current_user.tenant.get_settings()
    wa_url = None
    if cfg.get('whatsapp_notify') and sale.customer and sale.customer.phone:
        phone = ''.join(filter(str.isdigit, sale.customer.phone))
        if not phone.startswith('55'):
            phone = '55' + phone
        itens = ', '.join(f'{int(i.quantity)}x {i.product_name}' for i in sale.items)
        pgto_map = {
            'dinheiro': 'Dinheiro', 'cartao': 'Cartão', 'pix': 'Pix',
            'conta': 'Conta', 'pelo_app': 'Pelo app',
            'entrega_dinheiro': 'Dinheiro na entrega',
            'entrega_cartao': 'Cartão na entrega',
            'entrega_pix': 'Pix na entrega',
        }
        pagamento = pgto_map.get(sale.payment_method, sale.payment_method)
        total = f'R$ {sale.total:.2f}'.replace('.', ',')
        msg_tpl = cfg.get('whatsapp_msg') or 'Olá {cliente}! Seu pedido saiu para entrega com o motoboy {motoboy}. Em breve chegará até você!'
        msg = (msg_tpl
               .replace('{cliente}', sale.customer.name)
               .replace('{motoboy}', motoboy.name if motoboy else 'nosso entregador')
               .replace('{itens}', itens)
               .replace('{pagamento}', pagamento)
               .replace('{total}', total))
        import urllib.parse
        wa_url = f'whatsapp://send?phone={phone}&text={urllib.parse.quote(msg)}'

    _emit_entregas(tid())
    return jsonify({'ok': True, 'wa_url': wa_url, 'sale_id': sale.id})

@despacho_bp.route('/<int:sale_id>/concluir', methods=['POST'])
@login_required
def concluir(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    sale.delivered_at = datetime.now()
    db.session.commit()
    _emit_entregas(tid())
    return jsonify({'ok': True, 'sale_id': sale.id})


def _emit_entregas(tenant_id):
    try:
        from app.socket_instance import socketio
        base = Sale.query.filter_by(tenant_id=tenant_id, status='confirmed', delivery_mode='entrega')
        pendentes = base.filter(Sale.dispatched_at == None).count()
        retorno   = base.filter(Sale.dispatched_at != None, Sale.delivered_at == None).count()
        socketio.emit('entregas_update', {'pendentes': pendentes, 'retorno': retorno},
                      room=f'tenant_{tenant_id}')
    except Exception:
        pass
