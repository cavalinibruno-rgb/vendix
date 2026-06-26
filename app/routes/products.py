from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, Response
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from PIL import Image
import io
import json
from app import db
from app import r2
from app.models.product import Product, ProductType, Brand
from app.models.combo import ComboItem

products_bp = Blueprint('products', __name__, url_prefix='/produtos')

def tenant_id():
    return current_user.tenant_id

def _comprimir_imagem(file_storage, max_size=(600, 600), quality=75):
    """Redimensiona e comprime imagem para JPEG. Retorna (bytes, mime)."""
    img = Image.open(file_storage)
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    img.thumbnail(max_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality, optimize=True)
    return buf.getvalue(), 'image/jpeg'

def _gerar_thumbnail(image_bytes, size=(80, 80), quality=55):
    """Gera miniatura ultra-compacta para embutir em JSON como base64."""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    img.thumbnail(size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality, optimize=True)
    import base64
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()

@products_bp.route('/')
@login_required
def index():
    types  = ProductType.query.filter_by(tenant_id=tenant_id()).order_by(ProductType.name).all()
    brands = Brand.query.filter_by(tenant_id=tenant_id()).order_by(Brand.name).all()
    tipo_id  = request.args.get('tipo', type=int)
    marca_id = request.args.get('marca', type=int)
    query = Product.query.filter_by(tenant_id=tenant_id())
    if tipo_id:
        query = query.filter_by(type_id=tipo_id)
    if marca_id:
        query = query.filter_by(brand_id=marca_id)
    products = query.order_by(Product.name).all()

    # Mapa estoque dos pais para calcular estoque efetivo dos packs
    parent_ids = {p.pack_parent_id for p in products if p.pack_parent_id}
    parent_stock_map = {}
    parent_min_map   = {}
    if parent_ids:
        for pr in Product.query.filter(Product.id.in_(parent_ids)).with_entities(
                Product.id, Product.stock_quantity, Product.min_stock).all():
            parent_stock_map[pr.id] = pr.stock_quantity
            parent_min_map[pr.id]   = pr.min_stock

    def eff_stock(p):
        if p.pack_parent_id and p.pack_qty:
            return parent_stock_map.get(p.pack_parent_id, 0) // p.pack_qty
        return p.stock_quantity

    def eff_min(p):
        if p.pack_parent_id and p.pack_qty:
            return parent_min_map.get(p.pack_parent_id, 0) // p.pack_qty
        return p.min_stock

    return render_template('products/index.html', products=products, types=types, brands=brands,
                           tipo_id=tipo_id, marca_id=marca_id,
                           eff_stock=eff_stock, eff_min=eff_min)

@products_bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    types  = ProductType.query.filter_by(tenant_id=tenant_id()).order_by(ProductType.name).all()
    brands = Brand.query.filter_by(tenant_id=tenant_id()).order_by(Brand.name).all()
    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        type_id     = request.form.get('type_id') or None
        brand_id    = request.form.get('brand_id') or None
        sale_price       = float(request.form.get('sale_price', 0) or 0)
        sale_price_card  = float(request.form.get('sale_price_card', 0) or 0)
        sale_price_event = float(request.form.get('sale_price_event', 0) or 0)
        cost_price       = float(request.form.get('cost_price', 0) or 0)
        stock           = int(request.form.get('stock_quantity', 0) or 0)
        min_stock       = int(request.form.get('min_stock', 0) or 0)
        description     = request.form.get('description', '').strip()

        if not name:
            flash('Nome do produto é obrigatório.', 'danger')
            return render_template('products/form.html', types=types, brands=brands)

        combo_json = request.form.get('combo_components', '[]')
        try:
            combo_components = json.loads(combo_json)
        except Exception:
            combo_components = []
        is_combo = len(combo_components) > 0
        if is_combo:
            stock = 0

        product = Product(
            tenant_id=tenant_id(),
            type_id=type_id,
            brand_id=brand_id,
            name=name,
            description=description,
            sale_price=sale_price,
            sale_price_card=sale_price_card,
            sale_price_event=sale_price_event,
            cost_price=cost_price,
            stock_quantity=stock,
            min_stock=min_stock,
        )
        db.session.add(product)
        db.session.flush()
        def _salvar_foto(prod, file_field):
            from flask import current_app
            foto = request.files.get(file_field)
            current_app.logger.info(f'[_salvar_foto] field={file_field} foto={foto} filename={foto.filename if foto else None}')
            if foto and foto.filename:
                try:
                    img_bytes, mime = _comprimir_imagem(foto)
                    key = r2.unique_key('produtos', '.jpg')
                    try:
                        prod.image_url = r2.upload(img_bytes, key, mime)
                        prod.thumbnail_data = _gerar_thumbnail(img_bytes).encode()
                        current_app.logger.info(f'[_salvar_foto] R2 ok: {prod.image_url}')
                    except Exception as e2:
                        current_app.logger.warning(f'[_salvar_foto] R2 falhou ({e2}), usando BYTEA')
                        prod.image_data = img_bytes
                        prod.image_mime = mime
                        prod.thumbnail_data = _gerar_thumbnail(img_bytes).encode()
                except Exception as e:
                    current_app.logger.error(f'[_salvar_foto] erro geral: {e}')

        tem_pack = request.form.get('tem_pack') == '1'

        # Coleta packs[0][qty], packs[1][qty], etc.
        packs_data = []
        if tem_pack and not is_combo:
            i = 0
            while True:
                qty_str = request.form.get(f'packs[{i}][qty]')
                if qty_str is None:
                    break
                qty = int(qty_str or 0)
                if qty > 1:
                    packs_data.append({
                        'qty':        qty,
                        'preco':      float(request.form.get(f'packs[{i}][preco]', 0) or 0),
                        'preco_card': float(request.form.get(f'packs[{i}][preco_card]', 0) or 0),
                        'preco_event':float(request.form.get(f'packs[{i}][preco_event]', 0) or 0),
                        'foto_key':   f'packs[{i}][foto]',
                    })
                i += 1

        if tem_pack:
            _salvar_foto(product, 'imagem_unidade')
        else:
            _salvar_foto(product, 'imagem')

        for comp in combo_components:
            ci = ComboItem(combo_id=product.id,
                           component_id=int(comp['product_id']),
                           quantity=float(comp['quantity']))
            db.session.add(ci)

        # Cria um produto pack para cada entrada
        for pd in packs_data:
            pack = Product(
                tenant_id        = tenant_id(),
                type_id          = type_id,
                brand_id         = brand_id,
                name             = f'Pack c/ {pd["qty"]} {name}',
                description      = f'Pack com {pd["qty"]} unidades de {name}.',
                sale_price       = pd['preco'],
                sale_price_card  = pd['preco_card'],
                sale_price_event = pd['preco_event'],
                cost_price       = cost_price * pd['qty'],
                stock_quantity   = 0,
                min_stock        = 0,
                pack_parent_id   = product.id,
                pack_qty         = pd['qty'],
            )
            db.session.add(pack)
            db.session.flush()
            _salvar_foto(pack, pd['foto_key'])

        db.session.commit()
        if packs_data:
            nomes = ', '.join(f'Pack c/ {p["qty"]}' for p in packs_data)
            flash(f'Produto "{name}" e packs ({nomes}) cadastrados com sucesso!', 'success')
        else:
            flash(f'Produto "{name}" cadastrado com sucesso!', 'success')
        return redirect(url_for('products.index'))

    return render_template('products/form.html', types=types, brands=brands, product=None)

@products_bp.route('/<int:product_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(product_id):
    product = Product.query.filter_by(id=product_id, tenant_id=tenant_id()).first_or_404()
    types   = ProductType.query.filter_by(tenant_id=tenant_id()).order_by(ProductType.name).all()
    brands  = Brand.query.filter_by(tenant_id=tenant_id()).order_by(Brand.name).all()
    if request.method == 'POST':
        product.name           = request.form.get('name', '').strip()
        product.type_id        = request.form.get('type_id') or None
        product.brand_id       = request.form.get('brand_id') or None
        product.sale_price       = float(request.form.get('sale_price', 0) or 0)
        product.sale_price_card  = float(request.form.get('sale_price_card', 0) or 0)
        product.sale_price_event = float(request.form.get('sale_price_event', 0) or 0)
        product.cost_price       = float(request.form.get('cost_price', 0) or 0)
        product.stock_quantity = int(request.form.get('stock_quantity', 0) or 0)
        product.min_stock      = int(request.form.get('min_stock', 0) or 0)
        product.description    = request.form.get('description', '').strip()
        foto = request.files.get('imagem')
        if foto and foto.filename:
            img_bytes, mime = _comprimir_imagem(foto)
            key = r2.unique_key('produtos', '.jpg')
            try:
                product.image_url = r2.upload(img_bytes, key, mime)
                product.thumbnail_data = _gerar_thumbnail(img_bytes).encode()
            except Exception:
                product.image_data = img_bytes
                product.image_mime = mime
                product.thumbnail_data = _gerar_thumbnail(img_bytes).encode()

        combo_json = request.form.get('combo_components', '[]')
        try:
            combo_components = json.loads(combo_json)
        except Exception:
            combo_components = []
        ComboItem.query.filter_by(combo_id=product.id).delete()
        for comp in combo_components:
            ci = ComboItem(combo_id=product.id,
                           component_id=int(comp['product_id']),
                           quantity=float(comp['quantity']))
            db.session.add(ci)
        if combo_components:
            product.stock_quantity = 0

        db.session.commit()
        flash('Produto atualizado com sucesso!', 'success')
        return redirect(url_for('products.index'))

    existing_components = [
        {'product_id': ci.component_id, 'name': ci.component.name,
         'quantity': ci.quantity, 'cost_price': ci.component.cost_price or 0}
        for ci in product.combo_items
    ]
    return render_template('products/form.html', types=types, brands=brands, product=product,
                           existing_components=existing_components)

@products_bp.route('/<int:product_id>/excluir', methods=['POST'])
@login_required
def excluir(product_id):
    from app.models.sale import SaleItem
    from app.models.stock import StockMovement
    product = Product.query.filter_by(id=product_id, tenant_id=tenant_id()).first_or_404()
    # Desvincula packs filhos
    Product.query.filter_by(pack_parent_id=product.id, tenant_id=tenant_id()).update(
        {'pack_parent_id': None, 'pack_qty': None}
    )
    # Remove combo items que usam este produto (como combo ou componente)
    ComboItem.query.filter_by(component_id=product.id).delete()
    ComboItem.query.filter_by(combo_id=product.id).delete()
    # Desvincula itens de venda e movimentações (mantém histórico, só remove FK)
    SaleItem.query.filter_by(product_id=product.id).update({'product_id': None})
    StockMovement.query.filter_by(product_id=product.id).update({'product_id': None})
    db.session.delete(product)
    db.session.commit()
    flash('Produto removido.', 'success')
    return redirect(url_for('products.index'))

# ── Tipos ─────────────────────────────────────────────
@products_bp.route('/tipos')
@login_required
def tipos():
    types = ProductType.query.filter_by(tenant_id=tenant_id()).order_by(ProductType.name).all()
    return render_template('products/tipos.html', types=types)

@products_bp.route('/tipos/novo', methods=['POST'])
@login_required
def tipo_novo():
    name = request.form.get('name', '').strip()
    if name:
        t = ProductType(tenant_id=tenant_id(), name=name)
        db.session.add(t)
        db.session.commit()
        flash(f'Categoria "{name}" criada!', 'success')
    return redirect(url_for('products.tipos'))

@products_bp.route('/tipos/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def tipo_excluir(tipo_id):
    t = ProductType.query.filter_by(id=tipo_id, tenant_id=tenant_id()).first_or_404()
    db.session.delete(t)
    db.session.commit()
    flash('Categoria removida.', 'success')
    return redirect(url_for('products.tipos'))

# ── Marcas ────────────────────────────────────────────
@products_bp.route('/marcas')
@login_required
def marcas():
    brands = Brand.query.filter_by(tenant_id=tenant_id()).order_by(Brand.name).all()
    return render_template('products/marcas.html', brands=brands)

@products_bp.route('/marcas/nova', methods=['POST'])
@login_required
def marca_nova():
    name = request.form.get('name', '').strip()
    if name:
        b = Brand(tenant_id=tenant_id(), name=name)
        db.session.add(b)
        db.session.commit()
        flash(f'Marca "{name}" criada!', 'success')
    return redirect(url_for('products.marcas'))

@products_bp.route('/marcas/<int:brand_id>/excluir', methods=['POST'])
@login_required
def marca_excluir(brand_id):
    b = Brand.query.filter_by(id=brand_id, tenant_id=tenant_id()).first_or_404()
    db.session.delete(b)
    db.session.commit()
    flash('Marca removida.', 'success')
    return redirect(url_for('products.marcas'))

# ── API busca produtos ────────────────────────────────
def _cols():
    """Colunas leves — exclui image_data para não trazer BYTEA na listagem."""
    return [Product.id, Product.name, Product.sale_price, Product.sale_price_card,
            Product.sale_price_event, Product.stock_quantity, Product.type_id, Product.brand_id,
            Product.image_url, Product.pack_parent_id, Product.pack_qty,
            ((Product.image_data != None) | (Product.image_url != None)).label('has_image')]

def _effective_stock(r, parent_stock_map):
    """Calcula estoque efetivo: pack usa estoque do pai ÷ pack_qty."""
    if r.pack_parent_id and r.pack_qty and r.pack_qty > 0:
        parent_stock = parent_stock_map.get(r.pack_parent_id, 0)
        return parent_stock // r.pack_qty
    return r.stock_quantity

def _pack_remainder(r, parent_stock_map):
    if r.pack_parent_id and r.pack_qty and r.pack_qty > 0:
        parent_stock = parent_stock_map.get(r.pack_parent_id, 0)
        return parent_stock % r.pack_qty
    return 0

def _build_parent_stock_map(rows):
    """Carrega estoques dos produtos pai referenciados por packs."""
    parent_ids = {r.pack_parent_id for r in rows if r.pack_parent_id}
    if not parent_ids:
        return {}
    parents = Product.query.filter(Product.id.in_(parent_ids)).with_entities(
        Product.id, Product.stock_quantity).all()
    return {p.id: p.stock_quantity for p in parents}

@products_bp.route('/api/buscar')
@login_required
def api_buscar():
    q        = request.args.get('q', '')
    tipo_id  = request.args.get('tipo', type=int)
    marca_id = request.args.get('marca', type=int)
    query = (db.session.query(*_cols())
             .filter(Product.tenant_id == tenant_id(), Product.active == True))
    if q:       query = query.filter(Product.name.ilike(f'%{q}%'))
    if tipo_id: query = query.filter(Product.type_id == tipo_id)
    if marca_id:query = query.filter(Product.brand_id == marca_id)
    rows = query.limit(20).all()

    tipos  = {t.id: t.name for t in ProductType.query.filter_by(tenant_id=tenant_id()).all()}
    marcas = {b.id: b.name for b in Brand.query.filter_by(tenant_id=tenant_id()).all()}

    extra = {p.id: p for p in Product.query.filter(
        Product.id.in_([r.id for r in rows]), Product.tenant_id == tenant_id()
    ).with_entities(Product.id, Product.cost_price, Product.sale_price_card).all()}

    psm = _build_parent_stock_map(rows)
    return jsonify([{
        'id': r.id, 'name': r.name,
        'sale_price': r.sale_price,
        'sale_price_card': (extra[r.id].sale_price_card or 0) if r.id in extra else 0,
        'cost_price': (extra[r.id].cost_price or 0) if r.id in extra else 0,
        'stock_quantity': _effective_stock(r, psm),
        'has_image': bool(r.has_image),
        'type': tipos.get(r.type_id, ''),
        'type_id': r.type_id,
        'brand': marcas.get(r.brand_id, ''),
    } for r in rows])

@products_bp.route('/api/todos')
@login_required
def api_todos():
    rows = (db.session.query(*_cols())
            .filter(Product.tenant_id == tenant_id(), Product.active == True)
            .order_by(Product.name).all())

    tipos  = {t.id: t.name for t in ProductType.query.filter_by(tenant_id=tenant_id()).all()}
    marcas = {b.id: b.name for b in Brand.query.filter_by(tenant_id=tenant_id()).all()}

    # Busca thumbnails — R2 (URL) tem prioridade; BYTEA como fallback legado
    ids_com_img = [r.id for r in rows if r.has_image]
    r2_urls = {r.id: r.image_url for r in rows if r.image_url}
    thumbs = {}
    if ids_com_img:
        ids_sem_r2 = [i for i in ids_com_img if i not in r2_urls]
        if ids_sem_r2:
            for p in Product.query.filter(Product.id.in_(ids_sem_r2)).with_entities(Product.id, Product.thumbnail_data, Product.image_data).all():
                if p.thumbnail_data:
                    thumbs[p.id] = p.thumbnail_data.decode()
                elif p.image_data:
                    t = _gerar_thumbnail(p.image_data)
                    thumbs[p.id] = t
                    Product.query.filter_by(id=p.id).update({'thumbnail_data': t.encode()})
            db.session.commit()

    psm = _build_parent_stock_map(rows)
    return jsonify([{
        'id': r.id, 'name': r.name,
        'sale_price': r.sale_price,
        'sale_price_card': r.sale_price_card or 0,
        'sale_price_event': r.sale_price_event or 0,
        'stock_quantity': _effective_stock(r, psm),
        'pack_remainder': _pack_remainder(r, psm) if r.pack_parent_id else 0,
        'thumbnail': r2_urls.get(r.id) or thumbs.get(r.id),
        'type_id': r.type_id,
        'type_name': tipos.get(r.type_id, 'Sem categoria'),
        'brand_id': r.brand_id,
        'brand_name': marcas.get(r.brand_id),
    } for r in rows])

@products_bp.route('/<int:product_id>/imagem')
def imagem(product_id):
    from flask import redirect as _redirect
    product = Product.query.filter_by(id=product_id).first_or_404()
    if product.image_url:
        return _redirect(product.image_url, 301)
    if not product.image_data:
        return '', 404
    resp = Response(product.image_data, mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'public, max-age=604800'
    return resp

@products_bp.route('/admin/recomprimir-imagens', methods=['POST'])
@login_required
def recomprimir_imagens():
    produtos = Product.query.filter(
        Product.tenant_id == tenant_id(),
        Product.image_data != None
    ).all()
    count = 0
    for p in produtos:
        try:
            dados, mime = _comprimir_imagem(io.BytesIO(p.image_data))
            p.image_data = dados
            p.image_mime = mime
            count += 1
        except Exception:
            pass
    db.session.commit()
    flash(f'{count} imagem(ns) recomprimida(s) com sucesso.', 'success')
    return redirect(url_for('products.index'))

@products_bp.route('/api/categorias')
@login_required
def api_categorias():
    types = ProductType.query.filter_by(tenant_id=tenant_id()).order_by(ProductType.name).all()
    return jsonify([{'id': t.id, 'name': t.name} for t in types])

@products_bp.route('/api/marcas')
@login_required
def api_marcas():
    brands = Brand.query.filter_by(tenant_id=tenant_id()).order_by(Brand.name).all()
    return jsonify([{'id': b.id, 'name': b.name} for b in brands])

@products_bp.route('/api/categoria-rapida', methods=['POST'])
@login_required
def api_categoria_rapida():
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'Nome obrigatório'}), 400
    existing = ProductType.query.filter_by(tenant_id=tenant_id(), name=name).first()
    if existing:
        return jsonify({'id': existing.id, 'name': existing.name})
    t = ProductType(tenant_id=tenant_id(), name=name)
    db.session.add(t)
    db.session.commit()
    return jsonify({'id': t.id, 'name': t.name})

@products_bp.route('/api/marca-rapida', methods=['POST'])
@login_required
def api_marca_rapida():
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'Nome obrigatório'}), 400
    existing = Brand.query.filter_by(tenant_id=tenant_id(), name=name).first()
    if existing:
        return jsonify({'id': existing.id, 'name': existing.name})
    b = Brand(tenant_id=tenant_id(), name=name)
    db.session.add(b)
    db.session.commit()
    return jsonify({'id': b.id, 'name': b.name})
