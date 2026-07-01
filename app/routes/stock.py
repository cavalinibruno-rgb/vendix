from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from app.auth_utils import autenticar_operador
from flask_login import login_required, current_user
from app import db
from app.models.product import Product, ProductType, Brand
from app.models.stock import StockMovement
from datetime import date, datetime

stock_bp = Blueprint('stock', __name__, url_prefix='/estoque')

def tid():
    return current_user.tenant_id

def registrar_movimento(tenant_id, product, tipo, quantidade, motivo, user=None):
    m = StockMovement(
        tenant_id    = tenant_id,
        product_id   = product.id,
        product_name = product.name,
        type         = tipo,
        quantity     = quantidade,
        motive       = motivo,
        user_id      = user.id if user else None,
        user_name    = (user.display_name or user.username) if user else None,
    )
    db.session.add(m)

@stock_bp.route('/')
@login_required
def index():
    q        = request.args.get('q', '')
    tipo_id  = request.args.get('tipo', type=int)
    marca_id = request.args.get('marca', type=int)
    tipos    = ProductType.query.filter_by(tenant_id=tid()).order_by(ProductType.name).all()
    marcas   = Brand.query.filter_by(tenant_id=tid()).order_by(Brand.name).all()
    todos_produtos = Product.query.filter_by(tenant_id=tid(), active=True).with_entities(
        Product.type_id, Product.brand_id).all()

    ordem    = request.args.get('ordem', '')

    from app.models.combo import ComboItem
    combo_ids = db.session.query(ComboItem.combo_id).distinct()
    query = Product.query.filter_by(tenant_id=tid(), active=True).filter(~Product.id.in_(combo_ids))
    if q:
        query = query.filter(Product.name.ilike(f'%{q}%'))
    if tipo_id:
        query = query.filter_by(type_id=tipo_id)
    if marca_id:
        query = query.filter_by(brand_id=marca_id)
    if ordem == 'estoque_asc':
        query = query.order_by(Product.stock_quantity.asc())
    elif ordem == 'estoque_desc':
        query = query.order_by(Product.stock_quantity.desc())
    else:
        query = query.order_by(Product.name)
    produtos = query.all()

    # Estoque efetivo dos packs
    parent_ids = {p.pack_parent_id for p in produtos if p.pack_parent_id}
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

    # Movimentações com filtros
    filtro_tipo = request.args.get('mov_tipo', '')   # entrada | saida | ''
    filtro_data = request.args.get('mov_data', '')

    mov_query = StockMovement.query.filter_by(tenant_id=tid())
    if filtro_tipo:
        mov_query = mov_query.filter_by(type=filtro_tipo)
    if filtro_data:
        try:
            d = date.fromisoformat(filtro_data)
            mov_query = mov_query.filter(
                db.func.date(StockMovement.created_at) == d
            )
        except ValueError:
            pass
    movimentos = mov_query.order_by(StockMovement.created_at.desc()).limit(100).all()

    return render_template('stock/index.html',
        produtos=produtos, tipos=tipos, tipo_id=tipo_id, q=q, ordem=ordem,
        marcas=marcas, marca_id=marca_id, todos_produtos=todos_produtos,
        movimentos=movimentos, filtro_tipo=filtro_tipo, filtro_data=filtro_data,
        eff_stock=eff_stock, eff_min=eff_min,
    )

def _dados_relatorio():
    """Retorna (produtos, eff_stock, tenant, agora) para os relatórios de estoque."""
    from app.models.combo import ComboItem
    combo_ids = db.session.query(ComboItem.combo_id).distinct()
    produtos = Product.query\
        .filter(Product.tenant_id == tid(), Product.active == True)\
        .filter(~Product.id.in_(combo_ids))\
        .order_by(Product.name).all()

    parent_ids = {p.pack_parent_id for p in produtos if p.pack_parent_id}
    parent_stock_map = {}
    if parent_ids:
        for pr in Product.query.filter(Product.id.in_(parent_ids))\
                .with_entities(Product.id, Product.stock_quantity).all():
            parent_stock_map[pr.id] = pr.stock_quantity

    def eff_stock(p):
        if p.pack_parent_id and p.pack_qty:
            return parent_stock_map.get(p.pack_parent_id, 0) // p.pack_qty
        return p.stock_quantity

    return produtos, eff_stock, current_user.tenant, datetime.now()


@stock_bp.route('/relatorio', methods=['GET', 'POST'])
@login_required
def relatorio():
    if current_user.is_employee:
        abort(403)
    # "Valor de Estoque" mostra valores financeiros — exige senha do admin.
    if request.method != 'POST':
        return redirect(url_for('stock.index'))
    from app.models.user import User
    senha = request.form.get('senha', '')
    user = User.query.get(current_user.id)
    if not user or not user.check_password(senha):
        flash('Senha incorreta. Acesso ao Valor de Estoque negado.', 'danger')
        return redirect(url_for('stock.index'))
    produtos, eff_stock, tenant, agora = _dados_relatorio()
    return render_template('stock/relatorio.html',
        produtos=produtos, eff_stock=eff_stock, tenant=tenant, agora=agora)


@stock_bp.route('/balanco')
@login_required
def balanco():
    if current_user.is_employee:
        abort(403)
    produtos, eff_stock, tenant, agora = _dados_relatorio()
    return render_template('stock/balanco.html',
        produtos=produtos, eff_stock=eff_stock, tenant=tenant, agora=agora)


@stock_bp.route('/entrada', methods=['POST'])
@login_required
def entrada():
    MOTIVOS_ENTRADA = {'Compra de fornecedor', 'Devolução de cliente', 'Correção de estoque'}
    product_id   = request.form.get('product_id', type=int)
    quantidade   = int(request.form.get('quantidade', 0) or 0)
    motivo       = request.form.get('motivo', '').strip()
    op_username  = request.form.get('op_username', '').strip()
    op_password  = request.form.get('op_password', '').strip()

    if not product_id or quantidade <= 0:
        flash('Produto e quantidade são obrigatórios.', 'danger')
        return redirect(url_for('stock.index'))
    if motivo not in MOTIVOS_ENTRADA:
        flash('Selecione um motivo válido.', 'danger')
        return redirect(url_for('stock.index'))
    nome_resp, ok = autenticar_operador(tid(), op_username, op_password)
    if not ok:
        flash('Usuário ou senha incorretos.', 'danger')
        return redirect(url_for('stock.index'))

    produto = Product.query.filter_by(id=product_id, tenant_id=tid()).first_or_404()
    produto.stock_quantity += quantidade

    custo = request.form.get('custo', type=float)
    if custo is not None and custo >= 0:
        produto.cost_price = custo

    from app.models.stock import StockMovement
    db.session.add(StockMovement(
        tenant_id    = tid(),
        product_id   = produto.id,
        product_name = produto.name,
        type         = 'entrada',
        quantity     = quantidade,
        motive       = motivo,
        user_id      = current_user.id,
        user_name    = nome_resp,
    ))
    db.session.commit()
    flash(f'Entrada de {quantidade} unidades de "{produto.name}" registrada por {nome_resp}.', 'success')
    return redirect(url_for('stock.index'))

@stock_bp.route('/<int:product_id>/ajustar', methods=['POST'])
@login_required
def ajustar(product_id):
    MOTIVOS_AJUSTE = {'Perda', 'Correção de estoque'}
    produto      = Product.query.filter_by(id=product_id, tenant_id=tid()).first_or_404()
    operacao     = request.form.get('operacao')
    valor        = int(request.form.get('valor', 0) or 0)
    motivo_txt   = request.form.get('motivo', '').strip()
    op_username  = request.form.get('op_username', '').strip()
    op_password  = request.form.get('op_password', '').strip()

    if motivo_txt not in MOTIVOS_AJUSTE:
        flash('Selecione um motivo válido.', 'danger')
        return redirect(url_for('stock.index'))
    nome_resp, ok = autenticar_operador(tid(), op_username, op_password)
    if not ok:
        flash('Usuário ou senha incorretos.', 'danger')
        return redirect(url_for('stock.index'))

    antes = produto.stock_quantity
    motivo = motivo_txt
    if operacao == 'adicionar':
        produto.stock_quantity += valor
        tipo = 'entrada'
    elif operacao == 'subtrair':
        produto.stock_quantity = max(0, produto.stock_quantity - valor)
        tipo = 'saida'
    elif operacao == 'definir':
        diff = valor - antes
        produto.stock_quantity = max(0, valor)
        tipo  = 'entrada' if diff >= 0 else 'saida'
        valor = abs(diff) if diff != 0 else 0

    if valor != 0:
        from app.models.stock import StockMovement
        db.session.add(StockMovement(
            tenant_id    = tid(),
            product_id   = produto.id,
            product_name = produto.name,
            type         = tipo,
            quantity     = valor,
            motive       = motivo,
            user_id      = current_user.id,
            user_name    = nome_resp,
        ))
    db.session.commit()
    flash(f'Estoque de "{produto.name}" atualizado por {nome_resp}.', 'success')
    return redirect(url_for('stock.index'))
