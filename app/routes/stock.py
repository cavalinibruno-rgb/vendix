from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models.product import Product

stock_bp = Blueprint('stock', __name__, url_prefix='/estoque')

def tid():
    return current_user.tenant_id

@stock_bp.route('/')
@login_required
def index():
    produtos = Product.query.filter_by(tenant_id=tid(), active=True)\
                            .order_by(Product.name).all()
    baixo = [p for p in produtos if p.stock_quantity <= p.min_stock]
    return render_template('stock/index.html', produtos=produtos, baixo=baixo)

@stock_bp.route('/<int:product_id>/ajustar', methods=['POST'])
@login_required
def ajustar(product_id):
    produto = Product.query.filter_by(id=product_id, tenant_id=tid()).first_or_404()
    operacao = request.form.get('operacao')  # adicionar | subtrair | definir
    valor = int(request.form.get('valor', 0) or 0)

    if operacao == 'adicionar':
        produto.stock_quantity += valor
    elif operacao == 'subtrair':
        produto.stock_quantity = max(0, produto.stock_quantity - valor)
    elif operacao == 'definir':
        produto.stock_quantity = max(0, valor)

    db.session.commit()
    flash(f'Estoque de "{produto.name}" atualizado para {produto.stock_quantity} unidades.', 'success')
    return redirect(url_for('stock.index'))
