from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.product import Product, ProductType
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
    tipos    = ProductType.query.filter_by(tenant_id=tid()).order_by(ProductType.name).all()

    ordem    = request.args.get('ordem', '')

    query = Product.query.filter_by(tenant_id=tid(), active=True)
    if q:
        query = query.filter(Product.name.ilike(f'%{q}%'))
    if tipo_id:
        query = query.filter_by(type_id=tipo_id)
    if ordem == 'estoque_asc':
        query = query.order_by(Product.stock_quantity.asc())
    elif ordem == 'estoque_desc':
        query = query.order_by(Product.stock_quantity.desc())
    else:
        query = query.order_by(Product.name)
    produtos = query.all()

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
        movimentos=movimentos, filtro_tipo=filtro_tipo, filtro_data=filtro_data,
    )

@stock_bp.route('/entrada', methods=['POST'])
@login_required
def entrada():
    product_id = request.form.get('product_id', type=int)
    quantidade = int(request.form.get('quantidade', 0) or 0)
    motivo     = request.form.get('motivo', '').strip() or 'Entrada de estoque'

    if not product_id or quantidade <= 0:
        flash('Produto e quantidade são obrigatórios.', 'danger')
        return redirect(url_for('stock.index'))

    produto = Product.query.filter_by(id=product_id, tenant_id=tid()).first_or_404()
    produto.stock_quantity += quantidade
    registrar_movimento(tid(), produto, 'entrada', quantidade, motivo, current_user)
    db.session.commit()
    flash(f'Entrada de {quantidade} unidades de "{produto.name}" registrada.', 'success')
    return redirect(url_for('stock.index'))

@stock_bp.route('/<int:product_id>/ajustar', methods=['POST'])
@login_required
def ajustar(product_id):
    produto    = Product.query.filter_by(id=product_id, tenant_id=tid()).first_or_404()
    operacao   = request.form.get('operacao')
    valor      = int(request.form.get('valor', 0) or 0)
    motivo_txt = request.form.get('motivo', '').strip()

    antes = produto.stock_quantity
    if operacao == 'adicionar':
        produto.stock_quantity += valor
        tipo   = 'entrada'
        motivo = motivo_txt or 'Ajuste manual (adição)'
    elif operacao == 'subtrair':
        produto.stock_quantity = max(0, produto.stock_quantity - valor)
        tipo   = 'saida'
        motivo = motivo_txt or 'Ajuste manual (subtração)'
    elif operacao == 'definir':
        diff = valor - antes
        produto.stock_quantity = max(0, valor)
        tipo   = 'entrada' if diff >= 0 else 'saida'
        valor  = abs(diff) if diff != 0 else 0
        motivo = motivo_txt or f'Ajuste manual (definido para {produto.stock_quantity})'

    if valor != 0:
        registrar_movimento(tid(), produto, tipo, valor, motivo, current_user)
    db.session.commit()
    flash(f'Estoque de "{produto.name}" atualizado para {produto.stock_quantity} unidades.', 'success')
    return redirect(url_for('stock.index'))
