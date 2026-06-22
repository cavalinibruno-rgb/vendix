from flask import Blueprint, render_template, request, jsonify, redirect, url_for, abort, send_file, make_response
from app import db
from app.models.tenant import Tenant
from app.models.product import Product, ProductType
from app.models.customer import Neighborhood
from app.models.pedido_online import PedidoOnline
from app.models.sale import Sale
import json, io

loja_bp = Blueprint('loja', __name__, url_prefix='/loja')


def _get_tenant(slug):
    return Tenant.query.filter_by(slug=slug).first_or_404()


# ── Cardápio público ────────────────────────────────────
@loja_bp.route('/<slug>')
def cardapio(slug):
    tenant = _get_tenant(slug)
    categorias   = ProductType.query.filter_by(tenant_id=tenant.id).order_by(ProductType.name).all()
    bairros      = Neighborhood.query.filter_by(tenant_id=tenant.id).order_by(Neighborhood.name).all()
    return render_template('loja/cardapio.html',
        tenant=tenant, categorias=categorias, bairros=bairros)


# ── API pública: lista de produtos ─────────────────────
@loja_bp.route('/<slug>/produtos')
def api_produtos(slug):
    tenant   = _get_tenant(slug)
    produtos = Product.query.filter_by(tenant_id=tenant.id, active=True).order_by(Product.name).all()
    out = []
    for p in produtos:
        has_foto = bool(p.thumbnail_data or p.image_data)
        out.append({
            'id':        p.id,
            'name':      p.name,
            'price':     p.sale_price,
            'type_id':   p.type_id,
            'type_name': p.type.name if p.type else None,
            'thumb':     f'/loja/{slug}/produto/{p.id}/foto' if has_foto else None,
        })
    return jsonify(out)


@loja_bp.route('/<slug>/produto/<int:produto_id>/foto')
def foto_produto(slug, produto_id):
    tenant = _get_tenant(slug)
    p = Product.query.filter_by(id=produto_id, tenant_id=tenant.id).first_or_404()
    data = p.thumbnail_data or p.image_data
    if not data:
        abort(404)
    mime = p.image_mime or 'image/jpeg'
    resp = make_response(data)
    resp.headers['Content-Type'] = mime
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


# ── Fazer pedido ────────────────────────────────────────
@loja_bp.route('/<slug>/pedido', methods=['POST'])
def fazer_pedido(slug):
    tenant = _get_tenant(slug)
    data   = request.get_json() or {}

    cliente_nome   = (data.get('cliente_nome') or '').strip()
    cliente_tel    = (data.get('cliente_tel') or '').strip()
    bairro_id      = data.get('bairro_id') or None
    endereco       = (data.get('endereco') or '').strip()
    payment_method = data.get('payment_method', 'entrega_dinheiro')
    troco_para     = float(data.get('troco_para') or 0) or None
    notes          = (data.get('notes') or '').strip()
    items_raw      = data.get('items', [])

    if not cliente_nome:
        return jsonify({'error': 'Informe seu nome.'}), 400
    if not items_raw:
        return jsonify({'error': 'Carrinho vazio.'}), 400

    # Taxa de entrega
    taxa_entrega = 0.0
    bairro_nome  = ''
    if bairro_id:
        n = Neighborhood.query.filter_by(id=bairro_id, tenant_id=tenant.id).first()
        if n:
            taxa_entrega = n.delivery_fee
            bairro_nome  = n.name

    # Valida itens e calcula subtotal
    subtotal = 0.0
    items_ok = []
    for i in items_raw:
        pid  = i.get('product_id')
        qty  = float(i.get('quantity', 1))
        prod = Product.query.filter_by(id=pid, tenant_id=tenant.id, active=True).first()
        if not prod or qty <= 0:
            continue
        line = round(prod.sale_price * qty, 2)
        subtotal += line
        items_ok.append({
            'product_id': prod.id,
            'name':       prod.name,
            'unit_price': prod.sale_price,
            'quantity':   qty,
            'total':      line,
        })

    if not items_ok:
        return jsonify({'error': 'Nenhum produto válido.'}), 400

    total = round(subtotal + taxa_entrega, 2)

    pedido = PedidoOnline(
        tenant_id      = tenant.id,
        cliente_nome   = cliente_nome,
        cliente_tel    = cliente_tel,
        bairro_id      = bairro_id,
        bairro_nome    = bairro_nome,
        endereco       = endereco,
        taxa_entrega   = taxa_entrega,
        payment_method = payment_method,
        troco_para     = troco_para,
        items_json     = json.dumps(items_ok),
        subtotal       = subtotal,
        total          = total,
        notes          = notes,
        status         = 'pending',
    )
    db.session.add(pedido)
    db.session.commit()
    return jsonify({'pedido_id': pedido.id})


# ── Acompanhar pedido (cliente) ─────────────────────────
@loja_bp.route('/<slug>/pedido/<int:pedido_id>/acompanhar')
def acompanhar(slug, pedido_id):
    tenant = _get_tenant(slug)
    pedido = PedidoOnline.query.filter_by(id=pedido_id, tenant_id=tenant.id).first_or_404()
    return render_template('loja/acompanhar.html', tenant=tenant, pedido=pedido)


# ── Status polling (cliente) ────────────────────────────
@loja_bp.route('/<slug>/pedido/<int:pedido_id>/status')
def pedido_status(slug, pedido_id):
    tenant = _get_tenant(slug)
    pedido = PedidoOnline.query.filter_by(id=pedido_id, tenant_id=tenant.id).first_or_404()

    status = pedido.status
    dispatched_at = None

    # Se foi aceito e a venda foi despachada pelo módulo de Entregas
    if pedido.sale_id and status == 'accepted':
        sale = Sale.query.get(pedido.sale_id)
        if sale and sale.dispatched_at:
            status = 'dispatched'
            dispatched_at = sale.dispatched_at.strftime('%H:%M')

    return jsonify({
        'status':       status,
        'accepted_at':  pedido.accepted_at.strftime('%H:%M') if pedido.accepted_at else None,
        'dispatched_at': dispatched_at,
        'reject_reason': pedido.reject_reason,
    })
