from flask import Blueprint, render_template, request, jsonify, redirect, url_for, abort, send_file, make_response
from app import db, limiter, csrf
from app.models.tenant import Tenant
from app.models.product import Product, ProductType
from app.models.customer import Neighborhood
from app.models.pedido_online import PedidoOnline
from app.models.sale import Sale
from app.models.cash import CashRegister
from app.models.coupon import Coupon
import json, io, os, requests
from PIL import Image

loja_bp = Blueprint('loja', __name__, url_prefix='/loja')


def _get_tenant(slug):
    return Tenant.query.filter_by(slug=slug).first_or_404()


# ── Cardápio público ────────────────────────────────────
@loja_bp.route('/<slug>')
def cardapio(slug):
    tenant = _get_tenant(slug)
    caixa_aberto = CashRegister.query.filter_by(tenant_id=tenant.id, status='open').first() is not None
    categorias   = ProductType.query.filter_by(tenant_id=tenant.id).order_by(ProductType.name).all()
    bairros      = Neighborhood.query.filter_by(tenant_id=tenant.id).order_by(Neighborhood.name).all()
    return render_template('loja/cardapio.html',
        tenant=tenant, categorias=categorias, bairros=bairros, caixa_aberto=caixa_aberto)


# ── API pública: lista de produtos ─────────────────────
@loja_bp.route('/<slug>/produtos')
@limiter.limit("60 per minute")
def api_produtos(slug):
    tenant   = _get_tenant(slug)
    produtos = Product.query.filter_by(tenant_id=tenant.id, active=True).order_by(Product.name).all()
    out = []
    for p in produtos:
        if p.image_url:
            thumb = p.image_url
        elif p.image_data:
            thumb = f'/loja/{slug}/produto/{p.id}/foto'
        else:
            thumb = None
        out.append({
            'id':         p.id,
            'name':       p.name,
            'price':      p.sale_price,
            'price_cold': p.sale_price_cold or 0,
            'type_id':    p.type_id,
            'type_name':  p.type.name if p.type else None,
            'brand_id':   p.brand_id,
            'brand_name': p.brand.name if p.brand else None,
            'thumb':      thumb,
        })
    return jsonify(out)


@loja_bp.route('/<slug>/produto/<int:produto_id>/foto')
def foto_produto(slug, produto_id):
    tenant = _get_tenant(slug)
    p = Product.query.filter_by(id=produto_id, tenant_id=tenant.id).first_or_404()
    if not p.image_data:
        abort(404)
    try:
        img = Image.open(io.BytesIO(bytes(p.image_data)))
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        img.thumbnail((480, 480), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=82, optimize=True)
        resp = make_response(buf.getvalue())
    except Exception:
        resp = make_response(bytes(p.image_data))
    resp.headers['Content-Type'] = 'image/jpeg'
    resp.headers['Cache-Control'] = 'public, max-age=604800'  # 7 dias
    return resp


@loja_bp.route('/<slug>/logo')
def logo_publica(slug):
    tenant = _get_tenant(slug)
    if not tenant.logo_data:
        abort(404)
    resp = make_response(bytes(tenant.logo_data))
    resp.headers['Content-Type'] = tenant.logo_mime or 'image/png'
    resp.headers['Cache-Control'] = 'public, max-age=604800'
    return resp


# ── Geocodificação de CEP via ViaCEP + Nominatim (gratuito, sem chave) ──
_NOMINATIM_HEADERS = {'User-Agent': 'VendixApp/1.0 (contato@vendixapp.com.br)'}

@loja_bp.route('/<slug>/geocode-cep')
@limiter.limit("20 per minute")
def geocode_cep(slug):
    _get_tenant(slug)
    cep = request.args.get('cep', '').replace('-', '').strip()
    if len(cep) != 8:
        return jsonify({'error': 'CEP inválido'})
    try:
        # 1. ViaCEP: CEP → endereço
        via = requests.get(f'https://viacep.com.br/ws/{cep}/json/', timeout=5).json()
        if via.get('erro'):
            return jsonify({'error': 'CEP não encontrado'})
        logradouro = via.get('logradouro', '')
        localidade = via.get('localidade', '')
        uf         = via.get('uf', '')
        query      = f"{logradouro}, {localidade}, {uf}, Brasil" if logradouro else f"{localidade}, {uf}, Brasil"

        # 2. Nominatim: endereço → lat/lng
        r = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={'q': query, 'format': 'json', 'limit': 1, 'countrycodes': 'br'},
            headers=_NOMINATIM_HEADERS,
            timeout=5
        )
        results = r.json()
        if results:
            return jsonify({'lat': float(results[0]['lat']), 'lng': float(results[0]['lon'])})
        return jsonify({'error': 'CEP não encontrado'})
    except Exception:
        return jsonify({'error': 'Erro ao consultar CEP. Tente novamente.'})


@loja_bp.route('/<slug>/reverse-geocode')
@limiter.limit("20 per minute")
def reverse_geocode(slug):
    _get_tenant(slug)
    lat = request.args.get('lat', '')
    lng = request.args.get('lng', '')
    key = os.environ.get('GOOGLE_MAPS_KEY', '')
    if not key:
        return jsonify({'error': 'Geocoding não configurado'})
    try:
        r = requests.get(
            'https://maps.googleapis.com/maps/api/geocode/json',
            params={'latlng': f'{lat},{lng}', 'key': key, 'language': 'pt-BR'},
            timeout=5
        )
        data = r.json()
        if data.get('status') == 'OK' and data.get('results'):
            components = data['results'][0].get('address_components', [])
            rua = numero = bairro = ''
            for c in components:
                types = c.get('types', [])
                if 'route' in types:
                    rua = c['long_name']
                elif 'street_number' in types:
                    numero = c['long_name']
                elif 'sublocality_level_1' in types or 'sublocality' in types:
                    bairro = c['long_name']
                elif 'neighborhood' in types and not bairro:
                    bairro = c['long_name']
            return jsonify({'rua': rua, 'numero': numero, 'bairro': bairro})
        return jsonify({'error': 'Endereço não encontrado'})
    except Exception:
        return jsonify({'error': 'Erro ao consultar localização. Tente novamente.'})


# ── Validar cupom (público) ────────────────────────────
@loja_bp.route('/<slug>/cupom/<code>')
def validar_cupom(slug, code):
    tenant = _get_tenant(slug)
    from datetime import datetime as _dt
    c = Coupon.query.filter_by(tenant_id=tenant.id, code=code.upper(), active=True).first()
    if not c:
        return jsonify({'error': 'Cupom inválido ou expirado.'})
    now = _dt.now()
    if c.starts_at and now < c.starts_at:
        return jsonify({'error': 'Este cupom ainda não está válido.'})
    if c.ends_at and now > c.ends_at:
        return jsonify({'error': 'Este cupom expirou.'})
    if c.max_uses and c.max_uses > 0 and (c.used_count or 0) >= c.max_uses:
        return jsonify({'error': 'Este cupom atingiu o limite de usos.'})
    return jsonify({'type': c.coupon_type, 'amount': c.amount})


# ── Fazer pedido ────────────────────────────────────────
@loja_bp.route('/<slug>/pedido', methods=['POST'])
@csrf.exempt
@limiter.limit("10 per minute; 50 per hora")
def fazer_pedido(slug):
    tenant = _get_tenant(slug)
    caixa_aberto = CashRegister.query.filter_by(tenant_id=tenant.id, status='open').first() is not None
    if not caixa_aberto:
        return jsonify({'error': 'A loja está offline no momento. Tente novamente mais tarde.'}), 503
    data   = request.get_json() or {}

    cliente_nome   = (data.get('cliente_nome') or '').strip()
    cliente_tel    = (data.get('cliente_tel') or '').strip()
    bairro_id      = data.get('bairro_id') or None
    endereco       = (data.get('endereco') or '').strip()
    rua            = (data.get('rua') or '').strip()
    numero         = (data.get('numero') or '').strip()
    complemento    = (data.get('complemento') or '').strip()
    payment_method = data.get('payment_method', 'entrega_dinheiro')
    troco_para     = float(data.get('troco_para') or 0) or None
    notes          = (data.get('notes') or '').strip()
    cupom_code     = (data.get('cupom_code') or '').strip().upper()
    items_raw      = data.get('items', [])
    geo_lat        = data.get('geo_lat')
    geo_lng        = data.get('geo_lng')

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
    elif geo_lat and geo_lng:
        # Recalcula taxa por distância server-side usando as coordenadas do cliente
        import math as _math
        try:
            cfg  = tenant.get_settings()
            lat1 = float(cfg.get('loja_lat', 0))
            lng1 = float(cfg.get('loja_lng', 0))
            lat2 = float(geo_lat)
            lng2 = float(geo_lng)
            if lat1 and lng1:
                dlat = _math.radians(lat2 - lat1)
                dlng = _math.radians(lng2 - lng1)
                a = _math.sin(dlat/2)**2 + _math.cos(_math.radians(lat1)) * _math.cos(_math.radians(lat2)) * _math.sin(dlng/2)**2
                dist_km = 6371 * 2 * _math.asin(_math.sqrt(a))
                zonas = cfg.get('zonas_entrega', [])
                for z in sorted(zonas, key=lambda z: z['max_km']):
                    if dist_km <= z['max_km']:
                        taxa_entrega = z['fee']
                        break
                else:
                    if zonas:
                        return jsonify({'error': 'Endereço fora da área de entrega.'}), 400
        except (ValueError, TypeError):
            pass

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

    # Aplica cupom de desconto
    desconto = 0.0
    cupom_obj = None
    if cupom_code:
        from datetime import datetime as _dt
        c = Coupon.query.filter_by(tenant_id=tenant.id, code=cupom_code, active=True).first()
        if c:
            now = _dt.now()
            limite_ok = not (c.max_uses and c.max_uses > 0 and (c.used_count or 0) >= c.max_uses)
            periodo_ok = (not c.starts_at or now >= c.starts_at) and (not c.ends_at or now <= c.ends_at)
            if limite_ok and periodo_ok:
                cupom_obj = c
                if c.coupon_type == 'percent':
                    desconto = round(subtotal * c.amount / 100, 2)
                else:
                    desconto = min(round(c.amount, 2), subtotal)

    total = round(max(0, subtotal + taxa_entrega - desconto), 2)

    import secrets as _secrets
    pedido = PedidoOnline(
        token          = _secrets.token_urlsafe(32),
        tenant_id      = tenant.id,
        cliente_nome   = cliente_nome,
        cliente_tel    = cliente_tel,
        bairro_id      = bairro_id,
        bairro_nome    = bairro_nome,
        endereco       = endereco,
        rua            = rua,
        numero         = numero,
        complemento    = complemento,
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

    # Incrementa contador de usos do cupom atomicamente
    if cupom_obj:
        cupom_obj.used_count = (cupom_obj.used_count or 0) + 1

    db.session.commit()
    return jsonify({'pedido_id': pedido.id, 'token': pedido.token})


# ── Taxa por distância (cliente) ───────────────────────
@loja_bp.route('/<slug>/taxa-distancia')
def taxa_distancia(slug):
    import math
    tenant = _get_tenant(slug)
    cfg    = tenant.get_settings()
    try:
        lat1 = float(cfg.get('loja_lat', 0))
        lng1 = float(cfg.get('loja_lng', 0))
        lat2 = float(request.args.get('lat', 0))
        lng2 = float(request.args.get('lng', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Coordenadas inválidas.'})
    if not lat1 or not lng1:
        return jsonify({'error': 'Loja sem localização configurada.'})
    # Haversine
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    dist_km = R * 2 * math.asin(math.sqrt(a))
    zonas = cfg.get('zonas_entrega', [])
    if not zonas:
        return jsonify({'dist_km': round(dist_km, 2), 'fee': 0, 'fora': False})
    for z in sorted(zonas, key=lambda z: z['max_km']):
        if dist_km <= z['max_km']:
            return jsonify({'dist_km': round(dist_km, 2), 'fee': z['fee'], 'fora': False})
    return jsonify({'dist_km': round(dist_km, 2), 'fee': 0, 'fora': True})


# ── Rastrear pedido por telefone ou número ──────────────
@loja_bp.route('/<slug>/rastrear')
def rastrear(slug):
    tenant = _get_tenant(slug)
    busca  = request.args.get('q', '').strip()
    erro   = None
    pedido = None

    if busca:
        # Tenta por ID numérico
        if busca.isdigit():
            pedido = PedidoOnline.query.filter_by(
                id=int(busca), tenant_id=tenant.id
            ).first()
        # Tenta por telefone (normaliza removendo não-dígitos)
        if not pedido:
            tel = ''.join(c for c in busca if c.isdigit())
            if tel:
                pedido = PedidoOnline.query.filter_by(
                    tenant_id=tenant.id, cliente_tel=busca
                ).order_by(PedidoOnline.created_at.desc()).first()
                if not pedido and tel != busca:
                    pedido = PedidoOnline.query.filter(
                        PedidoOnline.tenant_id == tenant.id,
                        PedidoOnline.cliente_tel.contains(tel[-8:])
                    ).order_by(PedidoOnline.created_at.desc()).first()

        if not pedido:
            erro = 'Pedido não encontrado. Verifique o número ou telefone.'
        else:
            # Verifica se já foi entregue
            if pedido.sale_id:
                sale = Sale.query.get(pedido.sale_id)
                if sale and sale.delivered_at:
                    return render_template('loja/rastrear.html',
                        tenant=tenant, pedido=None, entregue=True, busca=busca)
            token_acomp = pedido.token or str(pedido.id)
            return redirect(url_for('loja.acompanhar', slug=slug, token=token_acomp))

    return render_template('loja/rastrear.html',
        tenant=tenant, pedido=None, entregue=False, busca=busca, erro=erro)


# ── Acompanhar pedido (cliente) ─────────────────────────
@loja_bp.route('/<slug>/pedido/<token>/acompanhar')
def acompanhar(slug, token):
    tenant = _get_tenant(slug)
    # Suporte a pedidos antigos que usam ID numérico como token
    if token.isdigit():
        pedido = PedidoOnline.query.filter_by(id=int(token), tenant_id=tenant.id).first_or_404()
    else:
        pedido = PedidoOnline.query.filter_by(token=token, tenant_id=tenant.id).first_or_404()
    return render_template('loja/acompanhar.html', tenant=tenant, pedido=pedido)


# ── Status polling (cliente) ────────────────────────────
@loja_bp.route('/<slug>/pedido/<token>/status')
def pedido_status(slug, token):
    tenant = _get_tenant(slug)
    if token.isdigit():
        pedido = PedidoOnline.query.filter_by(id=int(token), tenant_id=tenant.id).first_or_404()
    else:
        pedido = PedidoOnline.query.filter_by(token=token, tenant_id=tenant.id).first_or_404()

    status = pedido.status
    dispatched_at = None

    # Se foi aceito e a venda foi despachada pelo módulo de Entregas
    delivered_at = None
    if pedido.sale_id and status == 'accepted':
        sale = Sale.query.get(pedido.sale_id)
        if sale and sale.delivered_at:
            status = 'delivered'
            dispatched_at = sale.dispatched_at.strftime('%H:%M') if sale.dispatched_at else None
            delivered_at  = sale.delivered_at.strftime('%H:%M')
        elif sale and sale.dispatched_at:
            status = 'dispatched'
            dispatched_at = sale.dispatched_at.strftime('%H:%M')

    resp = jsonify({
        'status':        status,
        'accepted_at':   pedido.accepted_at.strftime('%H:%M') if pedido.accepted_at else None,
        'dispatched_at': dispatched_at,
        'delivered_at':  delivered_at,
        'reject_reason': pedido.reject_reason,
    })
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp
