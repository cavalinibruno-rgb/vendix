from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.product import Product, ProductType

products_bp = Blueprint('products', __name__, url_prefix='/produtos')

def tenant_id():
    return current_user.tenant_id

@products_bp.route('/')
@login_required
def index():
    types = ProductType.query.filter_by(tenant_id=tenant_id()).order_by(ProductType.name).all()
    tipo_id = request.args.get('tipo', type=int)
    query = Product.query.filter_by(tenant_id=tenant_id())
    if tipo_id:
        query = query.filter_by(type_id=tipo_id)
    products = query.order_by(Product.name).all()
    return render_template('products/index.html', products=products, types=types, tipo_id=tipo_id)

@products_bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    types = ProductType.query.filter_by(tenant_id=tenant_id()).order_by(ProductType.name).all()
    if request.method == 'POST':
        name       = request.form.get('name', '').strip()
        type_id    = request.form.get('type_id') or None
        sale_price = float(request.form.get('sale_price', 0) or 0)
        cost_price = float(request.form.get('cost_price', 0) or 0)
        stock      = int(request.form.get('stock_quantity', 0) or 0)
        min_stock  = int(request.form.get('min_stock', 0) or 0)
        description= request.form.get('description', '').strip()

        if not name:
            flash('Nome do produto é obrigatório.', 'danger')
            return render_template('products/form.html', types=types)

        product = Product(
            tenant_id=tenant_id(),
            type_id=type_id,
            name=name,
            description=description,
            sale_price=sale_price,
            cost_price=cost_price,
            stock_quantity=stock,
            min_stock=min_stock,
        )
        db.session.add(product)
        db.session.commit()
        flash(f'Produto "{name}" cadastrado com sucesso!', 'success')
        return redirect(url_for('products.index'))

    return render_template('products/form.html', types=types, product=None)

@products_bp.route('/<int:product_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(product_id):
    product = Product.query.filter_by(id=product_id, tenant_id=tenant_id()).first_or_404()
    types   = ProductType.query.filter_by(tenant_id=tenant_id()).order_by(ProductType.name).all()
    if request.method == 'POST':
        product.name           = request.form.get('name', '').strip()
        product.type_id        = request.form.get('type_id') or None
        product.sale_price     = float(request.form.get('sale_price', 0) or 0)
        product.cost_price     = float(request.form.get('cost_price', 0) or 0)
        product.stock_quantity = int(request.form.get('stock_quantity', 0) or 0)
        product.min_stock      = int(request.form.get('min_stock', 0) or 0)
        product.description    = request.form.get('description', '').strip()
        db.session.commit()
        flash('Produto atualizado com sucesso!', 'success')
        return redirect(url_for('products.index'))
    return render_template('products/form.html', types=types, product=product)

@products_bp.route('/<int:product_id>/excluir', methods=['POST'])
@login_required
def excluir(product_id):
    product = Product.query.filter_by(id=product_id, tenant_id=tenant_id()).first_or_404()
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
        flash(f'Tipo "{name}" criado!', 'success')
    return redirect(url_for('products.tipos'))

@products_bp.route('/tipos/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def tipo_excluir(tipo_id):
    t = ProductType.query.filter_by(id=tipo_id, tenant_id=tenant_id()).first_or_404()
    db.session.delete(t)
    db.session.commit()
    flash('Tipo removido.', 'success')
    return redirect(url_for('products.tipos'))

# ── API busca produtos ────────────────────────────────
@products_bp.route('/api/buscar')
@login_required
def api_buscar():
    q       = request.args.get('q', '')
    tipo_id = request.args.get('tipo', type=int)
    query   = Product.query.filter_by(tenant_id=tenant_id(), active=True)
    if q:
        query = query.filter(Product.name.ilike(f'%{q}%'))
    if tipo_id:
        query = query.filter_by(type_id=tipo_id)
    products = query.limit(20).all()
    return jsonify([{
        'id': p.id, 'name': p.name,
        'sale_price': p.sale_price,
        'stock_quantity': p.stock_quantity,
        'type': p.type.name if p.type else ''
    } for p in products])
