from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, Response
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload, defer
from PIL import Image
import io
import json
import unicodedata
from datetime import datetime
from app import db
from app import r2
from app.models.product import Product, ProductType, Brand
from app.models.combo import ComboItem
from app.models.ingredient import Ingredient, ProductIngredient

products_bp = Blueprint('products', __name__, url_prefix='/produtos')

def tenant_id():
    return current_user.tenant_id

def _sem_acentos(s):
    return unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()

def ordem_categorias_key(t):
    """Ordem das categorias: Promoção fixa em 1º, Combos em 2º; depois a ordem
    manual do lojista (sort_order) e, sem ordem definida, alfabética."""
    n = (t.name or '').lower()
    if 'promo' in n:
        return (0, 0, '')
    if 'combo' in n:
        return (1, 0, '')
    return (2, t.sort_order if t.sort_order is not None else 10**9, _sem_acentos(t.name))

def _parse_promo_dt(value):
    """Converte datetime-local (YYYY-MM-DDTHH:MM) em datetime, ou None se vazio/inválido."""
    value = (value or '').strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

def _salvar_composicao(product_id, composicao_raw):
    """Salva composição da ficha técnica e retorna o custo calculado (ou None se vazia)."""
    if not (current_user.tenant and current_user.tenant.is_lanchonete):
        return None
    try:
        itens = json.loads(composicao_raw or '[]')
    except Exception:
        itens = []
    ProductIngredient.query.filter_by(product_id=product_id).delete()
    custo_total = 0.0
    for item in itens:
        ing_id = int(item.get('ingredient_id', 0))
        qty    = float(item.get('quantity', 1) or 1)
        ing    = Ingredient.query.filter_by(id=ing_id, tenant_id=tenant_id()).first()
        if not ing:
            continue
        pi = ProductIngredient(product_id=product_id, ingredient_id=ing_id, quantity=qty)
        db.session.add(pi)
        custo_total += ing.cost_price * qty
    return round(custo_total, 2) if itens else None


def _parse_addons(raw):
    """Valida os adicionais vindos do form (JSON) -> string JSON limpa, ou None.
    Formato: [{"name": str, "price": float>=0}]. So aplica se a loja for lanchonete."""
    if not (current_user.tenant and current_user.tenant.is_lanchonete):
        return None
    try:
        itens = json.loads(raw or '[]')
    except Exception:
        return None
    limpo = []
    for a in itens[:50]:
        nome = str(a.get('name', '')).strip()[:60]
        if not nome:
            continue
        try:
            preco = round(max(0.0, float(a.get('price', 0) or 0)), 2)
        except (TypeError, ValueError):
            preco = 0.0
        limpo.append({'name': nome, 'price': preco})
    return json.dumps(limpo, ensure_ascii=False) if limpo else None

# Magic bytes das imagens permitidas
_MAGIC_BYTES = {
    b'\xff\xd8\xff': 'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF': 'image/webp',  # RIFF....WEBP
}
_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

def _validar_imagem(file_storage):
    """Lê até 12 bytes para verificar magic bytes. Lança ValueError se inválido."""
    data = file_storage.read(12)
    file_storage.seek(0)
    if len(data) < 4:
        raise ValueError('Arquivo muito pequeno ou corrompido.')
    for magic, mime in _MAGIC_BYTES.items():
        if data.startswith(magic):
            # Webp: verifica RIFF....WEBP
            if magic == b'RIFF' and data[8:12] != b'WEBP':
                continue
            return mime
    raise ValueError('Tipo de arquivo não permitido. Envie uma imagem JPG, PNG, GIF ou WEBP.')

def _comprimir_imagem(file_storage, max_size=(600, 600), quality=75):
    """Valida, redimensiona e comprime imagem para JPEG. Retorna (bytes, mime)."""
    # Verifica tamanho antes de ler tudo
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > _MAX_UPLOAD_SIZE:
        raise ValueError(f'Imagem muito grande. Máximo permitido: 10 MB.')
    _validar_imagem(file_storage)
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
    # Filtros são aplicados no navegador (instantâneos, como no Nova Venda).
    # Os params da URL só pré-preenchem o formulário — o JS aplica na carga.
    q        = request.args.get('q', '').strip()
    tipo_id  = request.args.get('tipo', type=int)
    marca_id = request.args.get('marca', type=int)
    # Não carrega os blobs de imagem (a lista não exibe imagem) e traz
    # categoria/marca de uma vez para evitar N+1 de queries.
    products = (Product.query.filter_by(tenant_id=tenant_id())
                .options(defer(Product.image_data), defer(Product.thumbnail_data),
                         joinedload(Product.type), joinedload(Product.brand))
                .order_by(Product.sort_order.nulls_last(), Product.name).all())

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
                           q=q, tipo_id=tipo_id, marca_id=marca_id,
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
        sale_price_cold      = float(request.form.get('sale_price_cold', 0) or 0)
        sale_price_cold_card = float(request.form.get('sale_price_cold_card', 0) or 0)
        cost_price           = float(request.form.get('cost_price', 0) or 0)
        stock           = int(request.form.get('stock_quantity', 0) or 0)
        # Operador de caixa não define estoque no cadastro
        if current_user.is_employee:
            stock = 0
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
            sale_price_cold=sale_price_cold,
            sale_price_cold_card=sale_price_cold_card,
            cost_price=cost_price,
            stock_quantity=stock,
            min_stock=min_stock,
        )
        product.promo_starts_at = _parse_promo_dt(request.form.get('promo_inicio'))
        product.promo_ends_at   = _parse_promo_dt(request.form.get('promo_fim'))
        product.addons          = _parse_addons(request.form.get('addons_json', '[]'))
        db.session.add(product)
        db.session.flush()

        last_num = db.session.query(db.func.max(Product.product_number)).filter(
            Product.tenant_id == tenant_id(), Product.id != product.id
        ).scalar() or 0
        product.product_number = last_num + 1

        def _salvar_foto(prod, file_field):
            foto = request.files.get(file_field)
            if foto and foto.filename:
                try:
                    img_bytes, mime = _comprimir_imagem(foto)
                    key = r2.unique_key('produtos', '.jpg')
                    try:
                        prod.image_url = r2.upload(img_bytes, key, mime, long_cache=True)
                        prod.thumbnail_data = _gerar_thumbnail(img_bytes).encode()
                    except Exception:
                        prod.image_data = img_bytes
                        prod.image_mime = mime
                        prod.thumbnail_data = _gerar_thumbnail(img_bytes).encode()
                except ValueError as e:
                    flash(str(e), 'danger')
                except Exception:
                    flash('Erro ao processar imagem. Verifique o arquivo e tente novamente.', 'danger')

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
                    termo = request.form.get(f'packs[{i}][termo]', 'Pack').strip() or 'Pack'
                    if termo not in ('Pack', 'Caixa', 'Maço'):
                        termo = 'Pack'
                    packs_data.append({
                        'qty':        qty,
                        'termo':      termo,
                        'preco':      float(request.form.get(f'packs[{i}][preco]', 0) or 0),
                        'preco_card': float(request.form.get(f'packs[{i}][preco_card]', 0) or 0),
                        'preco_event':float(request.form.get(f'packs[{i}][preco_event]', 0) or 0),
                        'preco_cold':      float(request.form.get(f'packs[{i}][preco_cold]', 0) or 0),
                        'preco_cold_card': float(request.form.get(f'packs[{i}][preco_cold_card]', 0) or 0),
                        'foto_key':   f'packs[{i}][foto]',
                    })
                i += 1

        _salvar_foto(product, 'imagem')

        for comp in combo_components:
            ci = ComboItem(combo_id=product.id,
                           component_id=int(comp['product_id']),
                           quantity=float(comp['quantity']))
            db.session.add(ci)

        custo_comp = _salvar_composicao(product.id, request.form.get('composicao_json', '[]'))
        if custo_comp is not None:
            product.cost_price = custo_comp

        # Nome do conjunto conforme o termo escolhido:
        #   Maço → "Maço de {nome}" (sem quantidade)
        #   Pack/Caixa → "{termo} c/ {N} {nome}"
        def _nome_pack(termo, qty):
            if termo == 'Maço':
                return f'Maço de {name}'
            return f'{termo} c/ {qty} {name}'

        # Cria um produto pack para cada entrada
        for pd in packs_data:
            pack = Product(
                tenant_id        = tenant_id(),
                type_id          = type_id,
                brand_id         = brand_id,
                name             = _nome_pack(pd['termo'], pd['qty']),
                description      = f'{pd["termo"]} com {pd["qty"]} unidades de {name}.',
                sale_price       = pd['preco'],
                sale_price_card  = pd['preco_card'],
                sale_price_event = pd['preco_event'],
                sale_price_cold      = pd['preco_cold'],
                sale_price_cold_card = pd['preco_cold_card'],
                cost_price           = cost_price * pd['qty'],
                stock_quantity   = 0,
                min_stock        = 0,
                pack_parent_id   = product.id,
                pack_qty         = pd['qty'],
            )
            db.session.add(pack)
            db.session.flush()
            last_num = db.session.query(db.func.max(Product.product_number)).filter(
                Product.tenant_id == tenant_id(), Product.id != pack.id
            ).scalar() or 0
            pack.product_number = last_num + 1
            _salvar_foto(pack, pd['foto_key'])

        db.session.commit()
        if packs_data:
            nomes = ', '.join(_nome_pack(p['termo'], p['qty']) for p in packs_data)
            flash(f'Produto "{name}" e {nomes} cadastrados com sucesso!', 'success')
        else:
            flash(f'Produto "{name}" cadastrado com sucesso!', 'success')
        return redirect(url_for('products.index'))

    return render_template('products/form.html', types=types, brands=brands, product=None,
                           composicao_json='[]')

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
        product.sale_price_cold      = float(request.form.get('sale_price_cold', 0) or 0)
        product.sale_price_cold_card = float(request.form.get('sale_price_cold_card', 0) or 0)
        product.cost_price           = float(request.form.get('cost_price', 0) or 0)
        # Operador de caixa não pode alterar o Estoque Atual (mantém o valor existente)
        if not current_user.is_employee:
            product.stock_quantity = int(request.form.get('stock_quantity', 0) or 0)
        product.min_stock      = int(request.form.get('min_stock', 0) or 0)
        product.description    = request.form.get('description', '').strip()
        product.promo_starts_at = _parse_promo_dt(request.form.get('promo_inicio'))
        product.promo_ends_at   = _parse_promo_dt(request.form.get('promo_fim'))
        product.addons          = _parse_addons(request.form.get('addons_json', '[]'))
        foto = request.files.get('imagem')
        if foto and foto.filename:
            img_bytes, mime = _comprimir_imagem(foto)
            key = r2.unique_key('produtos', '.jpg')
            try:
                product.image_url = r2.upload(img_bytes, key, mime, long_cache=True)
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

        custo_comp = _salvar_composicao(product.id, request.form.get('composicao_json', '[]'))
        if custo_comp is not None:
            product.cost_price = custo_comp

        db.session.commit()
        flash('Produto atualizado com sucesso!', 'success')
        # Volta pra lista preservando o filtro (categoria/marca/busca/ordem) e
        # ancorado no produto editado, em vez de jogar tudo pro topo sem filtro.
        return_qs = request.form.get('return_qs', '')
        url = url_for('products.index')
        if return_qs:
            url += '?' + return_qs
        url += '#prod-%d' % product.id
        return redirect(url)

    existing_components = [
        {'product_id': ci.component_id, 'name': ci.component.name,
         'quantity': ci.quantity, 'cost_price': ci.component.cost_price or 0}
        for ci in product.combo_items
    ]
    existing_composicao = [
        {'ingredient_id': pi.ingredient_id, 'name': pi.ingredient.name,
         'unit': pi.ingredient.unit, 'cost_price': pi.ingredient.cost_price,
         'quantity': pi.quantity}
        for pi in ProductIngredient.query.filter_by(product_id=product.id).all()
        if pi.ingredient
    ]
    return render_template('products/form.html', types=types, brands=brands, product=product,
                           existing_components=existing_components,
                           composicao_json=json.dumps(existing_composicao),
                           return_qs=request.query_string.decode())

@products_bp.route('/reordenar', methods=['POST'])
@login_required
def reordenar():
    """Recebe lista de IDs na nova ordem e salva sort_order em cada um."""
    ids = request.json.get('ids', [])
    for pos, pid in enumerate(ids, start=1):
        p = Product.query.filter_by(id=int(pid), tenant_id=tenant_id()).first()
        if p:
            p.sort_order = pos
    db.session.commit()
    return jsonify(ok=True)


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
    types = ProductType.query.filter_by(tenant_id=tenant_id()).all()
    types.sort(key=ordem_categorias_key)
    return render_template('products/tipos.html', types=types)


@products_bp.route('/tipos/reordenar', methods=['POST'])
@login_required
def tipos_reordenar():
    """Salva a ordem manual (lista de ids na ordem desejada, só não-protegidas)."""
    ids = (request.get_json(silent=True) or {}).get('ordem', [])
    tipos_map = {t.id: t for t in ProductType.query.filter_by(tenant_id=tenant_id()).all()}
    pos = 0
    for tid_ in ids:
        t = tipos_map.get(int(tid_))
        if t and not t.protected:
            t.sort_order = pos
            pos += 1
    db.session.commit()
    return jsonify(ok=True)


@products_bp.route('/tipos/ordem-padrao', methods=['POST'])
@login_required
def tipos_ordem_padrao():
    """Volta ao padrão: Promoção/Combos no topo e o resto em ordem alfabética."""
    ProductType.query.filter_by(tenant_id=tenant_id()).update({'sort_order': None})
    db.session.commit()
    flash('Ordem das categorias restaurada para o padrão (alfabética).', 'success')
    return redirect(url_for('products.tipos'))

@products_bp.route('/tipos/novo', methods=['POST'])
@login_required
def tipo_novo():
    name = request.form.get('name', '').strip()
    if name:
        t = ProductType(tenant_id=tenant_id(), name=name)
        db.session.add(t)
        db.session.flush()
        last_num = db.session.query(db.func.max(ProductType.type_number)).filter(
            ProductType.tenant_id == tenant_id(), ProductType.id != t.id
        ).scalar() or 0
        t.type_number = last_num + 1
        db.session.commit()
        flash(f'Categoria "{name}" criada!', 'success')
    return redirect(url_for('products.tipos'))

@products_bp.route('/tipos/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def tipo_excluir(tipo_id):
    t = ProductType.query.filter_by(id=tipo_id, tenant_id=tenant_id()).first_or_404()
    if t.protected:
        flash('Esta categoria é nativa do sistema e não pode ser removida.', 'danger')
        return redirect(url_for('products.tipos'))
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
        db.session.flush()
        last_num = db.session.query(db.func.max(Brand.brand_number)).filter(
            Brand.tenant_id == tenant_id(), Brand.id != b.id
        ).scalar() or 0
        b.brand_number = last_num + 1
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
            Product.sale_price_event, Product.sale_price_cold, Product.sale_price_cold_card, Product.stock_quantity, Product.type_id, Product.brand_id,
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
    from sqlalchemy import or_
    agora = datetime.now()
    rows = (db.session.query(*_cols())
            .filter(Product.tenant_id == tenant_id(), Product.active == True)
            # Promoções fora da janela de validade não aparecem/vendem no PDV
            .filter(or_(Product.promo_starts_at == None, Product.promo_starts_at <= agora))
            .filter(or_(Product.promo_ends_at == None, Product.promo_ends_at >= agora))
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
        'sale_price_cold': r.sale_price_cold or 0,
        'sale_price_cold_card': r.sale_price_cold_card or 0,
        'stock_quantity': _effective_stock(r, psm),
        'pack_remainder': _pack_remainder(r, psm) if r.pack_parent_id else 0,
        'thumbnail': r2_urls.get(r.id) or thumbs.get(r.id),
        'type_id': r.type_id,
        'type_name': tipos.get(r.type_id, 'Sem categoria'),
        'brand_id': r.brand_id,
        'brand_name': marcas.get(r.brand_id),
    } for r in rows])

@products_bp.route('/<int:product_id>/imagem')
@login_required
def imagem(product_id):
    from flask import redirect as _redirect
    product = Product.query.filter_by(id=product_id, tenant_id=tenant_id()).first_or_404()
    if product.image_url:
        return _redirect(product.image_url, 301)
    if not product.image_data:
        return '', 404
    resp = Response(product.image_data, mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'private, max-age=604800'
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
    db.session.flush()
    last_num = db.session.query(db.func.max(ProductType.type_number)).filter(
        ProductType.tenant_id == tenant_id(), ProductType.id != t.id
    ).scalar() or 0
    t.type_number = last_num + 1
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
    db.session.flush()
    last_num = db.session.query(db.func.max(Brand.brand_number)).filter(
        Brand.tenant_id == tenant_id(), Brand.id != b.id
    ).scalar() or 0
    b.brand_number = last_num + 1
    db.session.commit()
    return jsonify({'id': b.id, 'name': b.name})


@products_bp.route('/<int:product_id>/toggle-online', methods=['POST'])
@login_required
def toggle_online(product_id):
    p = Product.query.filter_by(id=product_id, tenant_id=tenant_id()).first_or_404()
    p.online_active = not p.online_active
    db.session.commit()
    return jsonify({'online_active': p.online_active})
