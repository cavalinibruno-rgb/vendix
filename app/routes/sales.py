from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.sale import Sale, SaleItem
from app.models.product import Product
from app.models.customer import Customer

sales_bp = Blueprint('sales', __name__, url_prefix='/vendas')

def tid():
    return current_user.tenant_id

@sales_bp.route('/nova')
@login_required
def nova():
    return render_template('sales/nova.html')

@sales_bp.route('/confirmar', methods=['POST'])
@login_required
def confirmar():
    data = request.get_json()
    if not data or not data.get('items'):
        return jsonify({'error': 'Carrinho vazio'}), 400

    customer_id    = data.get('customer_id') or None
    delivery_mode  = data.get('delivery_mode', 'retirada')
    delivery_fee   = float(data.get('delivery_fee', 0))
    payment_method = data.get('payment_method', 'dinheiro')
    notes          = data.get('notes', '')
    items          = data.get('items', [])

    subtotal = sum(float(i['unit_price']) * float(i['quantity']) for i in items)
    total    = subtotal + (delivery_fee if delivery_mode == 'entrega' else 0)

    sale = Sale(
        tenant_id      = tid(),
        customer_id    = customer_id,
        delivery_mode  = delivery_mode,
        delivery_fee   = delivery_fee if delivery_mode == 'entrega' else 0,
        subtotal       = subtotal,
        total          = total,
        payment_method = payment_method,
        notes          = notes,
    )
    db.session.add(sale)
    db.session.flush()

    for i in items:
        item = SaleItem(
            sale_id      = sale.id,
            product_id   = i.get('product_id') or None,
            product_name = i['name'],
            unit_price   = float(i['unit_price']),
            quantity     = float(i['quantity']),
            total        = float(i['unit_price']) * float(i['quantity']),
        )
        db.session.add(item)

    db.session.commit()
    return jsonify({'sale_id': sale.id})

@sales_bp.route('/')
@login_required
def index():
    sales = Sale.query.filter_by(tenant_id=tid(), status='confirmed')\
                      .order_by(Sale.created_at.desc()).limit(100).all()
    return render_template('sales/index.html', sales=sales)

@sales_bp.route('/<int:sale_id>')
@login_required
def detalhe(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    return render_template('sales/detalhe.html', sale=sale)

@sales_bp.route('/<int:sale_id>/cancelar', methods=['POST'])
@login_required
def cancelar(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    sale.status = 'cancelled'
    db.session.commit()
    flash('Venda cancelada.', 'warning')
    return redirect(url_for('sales.index'))
