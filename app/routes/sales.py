from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.sale import Sale, SaleItem
from app.models.product import Product
from app.models.customer import Customer
from app.models.cash import CashRegister
from app.models.stock import StockMovement
from app.auth_utils import autenticar_operador

sales_bp = Blueprint('sales', __name__, url_prefix='/vendas')

def tid():
    return current_user.tenant_id

def _caixa_aberto():
    return CashRegister.query.filter_by(tenant_id=tid(), status='open').first()

@sales_bp.route('/nova')
@login_required
def nova():
    if not _caixa_aberto():
        flash('Abra o caixa antes de realizar uma venda.', 'warning')
        return redirect(url_for('cash.index'))
    return render_template('sales/nova.html')

@sales_bp.route('/confirmar', methods=['POST'])
@login_required
def confirmar():
    if not _caixa_aberto():
        return jsonify({'error': 'Caixa fechado. Abra o caixa antes de realizar uma venda.'}), 403

    data = request.get_json()
    if not data or not data.get('items'):
        return jsonify({'error': 'Carrinho vazio'}), 400

    customer_id    = data.get('customer_id') or None
    delivery_mode  = data.get('delivery_mode', 'retirada')
    delivery_fee   = float(data.get('delivery_fee', 0))
    payment_method = data.get('payment_method', 'dinheiro')
    notes          = data.get('notes', '')
    source         = data.get('source', 'loja')
    app_name       = data.get('app_name', '') if source == 'app' else None
    amount_paid    = float(data.get('amount_paid', 0) or 0) or None
    items          = data.get('items', [])

    subtotal = sum(float(i['unit_price']) * float(i['quantity']) for i in items)
    total    = subtotal + (delivery_fee if delivery_mode == 'entrega' else 0)

    caixa = _caixa_aberto()
    cashier = caixa.operator_name if caixa and caixa.operator_name else (current_user.display_name or current_user.username)

    sale = Sale(
        tenant_id      = tid(),
        customer_id    = customer_id,
        delivery_mode  = delivery_mode,
        delivery_fee   = delivery_fee if delivery_mode == 'entrega' else 0,
        subtotal       = subtotal,
        total          = total,
        payment_method = payment_method,
        notes          = notes,
        source         = source,
        app_name       = app_name,
        amount_paid    = amount_paid,
        change_amount  = round(amount_paid - total, 2) if amount_paid and amount_paid > total else None,
        cashier_name   = cashier,
    )
    db.session.add(sale)
    db.session.flush()

    for i in items:
        qty = float(i['quantity'])
        pid = i.get('product_id') or None
        prod = Product.query.filter_by(id=pid, tenant_id=tid()).first() if pid else None
        item = SaleItem(
            sale_id      = sale.id,
            product_id   = pid,
            product_name = i['name'],
            unit_price   = float(i['unit_price']),
            cost_price   = (prod.cost_price or 0) if prod else 0,
            quantity     = qty,
            total        = float(i['unit_price']) * qty,
        )
        db.session.add(item)

        # desconta estoque e registra movimentação
        if pid:
            if not prod:
                prod = Product.query.filter_by(id=pid, tenant_id=tid()).first()
            if prod:
                deducao = min(int(qty), prod.stock_quantity)
                prod.stock_quantity = max(0, prod.stock_quantity - int(qty))
                if source == 'app' and app_name:
                    mot = f'Venda App #{sale.id} ({app_name})'
                else:
                    mot = f'Venda #{sale.id}'
                mov = StockMovement(
                    tenant_id    = tid(),
                    product_id   = prod.id,
                    product_name = prod.name,
                    type         = 'saida',
                    quantity     = int(qty),
                    motive       = mot,
                    user_id      = current_user.id,
                    user_name    = current_user.display_name or current_user.username,
                )
                db.session.add(mov)

    db.session.commit()
    return jsonify({'sale_id': sale.id})

@sales_bp.route('/')
@login_required
def index():
    from datetime import date, datetime
    from app.models.cash import CashRegister

    data_str = request.args.get('data', date.today().isoformat())
    try:
        data_fil = date.fromisoformat(data_str)
    except ValueError:
        data_fil = date.today()

    inicio = datetime.combine(data_fil, datetime.min.time())
    fim    = datetime.combine(data_fil, datetime.max.time())

    # Modo restrito: config ativa + caixa aberto por funcionário
    tenant = current_user.tenant
    cfg = tenant.get_settings()
    caixa = CashRegister.query.filter_by(tenant_id=tid(), status='open').first()
    modo_restrito = (
        cfg.get('dashboard_operador_restrito') and
        caixa is not None and
        caixa.operator_employee_id is not None
    )

    limite = 15 if modo_restrito else 500

    sales = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.created_at >= inicio,
        Sale.created_at <= fim,
    ).order_by(Sale.created_at.desc()).limit(limite).all()

    from datetime import timedelta
    return render_template('sales/index.html',
        sales=sales,
        data_fil=data_fil,
        modo_restrito=modo_restrito,
        limite=limite,
        hoje=date.today().isoformat(),
        ontem=(date.today() - timedelta(days=1)).isoformat(),
    )

@sales_bp.route('/<int:sale_id>')
@login_required
def detalhe(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    return render_template('sales/detalhe.html', sale=sale)

@sales_bp.route('/<int:sale_id>/cancelar', methods=['POST'])
@login_required
def cancelar(sale_id):
    from datetime import datetime
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    motivo      = request.form.get('cancel_reason', '').strip()
    op_username = request.form.get('op_username', '').strip()
    op_password = request.form.get('op_password', '').strip()
    if not motivo:
        flash('Informe o motivo do cancelamento.', 'danger')
        return redirect(url_for('sales.detalhe', sale_id=sale_id))
    nome_resp, ok = autenticar_operador(tid(), op_username, op_password)
    if not ok:
        flash('Usuário ou senha incorretos.', 'danger')
        return redirect(url_for('sales.detalhe', sale_id=sale_id))
    sale.status = 'cancelled'
    sale.cancelled_at = datetime.now()
    sale.cancelled_by_id = current_user.id
    sale.cancelled_by_name = nome_resp
    sale.cancel_reason = motivo

    # Devolve estoque e registra movimentação
    for item in sale.items:
        if item.product_id:
            prod = Product.query.filter_by(id=item.product_id, tenant_id=tid()).first()
            if prod:
                prod.stock_quantity += int(item.quantity)
                mov = StockMovement(
                    tenant_id    = tid(),
                    product_id   = prod.id,
                    product_name = prod.name,
                    type         = 'entrada',
                    quantity     = int(item.quantity),
                    motive       = f'Cancelamento Venda #{sale.id} — {motivo}',
                    user_id      = current_user.id,
                    user_name    = current_user.display_name or current_user.username,
                )
                db.session.add(mov)

    db.session.commit()
    flash('Venda cancelada.', 'warning')
    return redirect(url_for('sales.index'))

@sales_bp.route('/cancelamentos')
@login_required
def cancelamentos():
    from datetime import date
    filtro_de  = request.args.get('de', '')
    filtro_ate = request.args.get('ate', '')

    query = Sale.query.filter_by(tenant_id=tid(), status='cancelled')

    if filtro_de:
        try:
            query = query.filter(Sale.cancelled_at >= filtro_de)
        except Exception:
            pass
    if filtro_ate:
        try:
            query = query.filter(db.func.date(Sale.cancelled_at) <= filtro_ate)
        except Exception:
            pass

    vendas = query.order_by(Sale.cancelled_at.desc()).all()
    total_cancelado = sum(v.total for v in vendas)

    return render_template('sales/cancelamentos.html',
        vendas=vendas, total_cancelado=total_cancelado,
        filtro_de=filtro_de, filtro_ate=filtro_ate)
