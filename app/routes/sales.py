from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.sale import Sale, SaleItem
from app.models.product import Product
from app.models.customer import Customer
from app.models.cash import CashRegister
from app.models.stock import StockMovement
from app.models.combo import ComboItem
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
    discount_type  = data.get('discount_type') or None   # 'value' | 'percent' | None
    discount_input = float(data.get('discount', 0) or 0)

    subtotal = sum(float(i['unit_price']) * float(i['quantity']) for i in items)

    if discount_type == 'percent':
        discount = round(subtotal * discount_input / 100, 2)
    elif discount_type == 'value':
        discount = min(discount_input, subtotal)
    else:
        discount = 0.0

    total = subtotal - discount + (delivery_fee if delivery_mode == 'entrega' else 0)
    total = max(total, 0)

    caixa = _caixa_aberto()
    cashier = caixa.operator_name if caixa and caixa.operator_name else (current_user.display_name or current_user.username)

    sale = Sale(
        tenant_id      = tid(),
        customer_id    = customer_id,
        delivery_mode  = delivery_mode,
        delivery_fee   = delivery_fee if delivery_mode == 'entrega' else 0,
        subtotal       = subtotal,
        discount       = discount,
        discount_type  = discount_type,
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
                mot = f'Venda App #{sale.id} ({app_name})' if source == 'app' and app_name else f'Venda #{sale.id}'
                combo_items = ComboItem.query.filter_by(combo_id=pid).all()
                if combo_items:
                    # Combo: deduz estoque dos componentes
                    for ci in combo_items:
                        comp = Product.query.filter_by(id=ci.component_id, tenant_id=tid()).first()
                        if comp:
                            total_deduct = int(ci.quantity * qty)
                            comp.stock_quantity = max(0, comp.stock_quantity - total_deduct)
                            db.session.add(StockMovement(
                                tenant_id    = tid(),
                                product_id   = comp.id,
                                product_name = comp.name,
                                type         = 'saida',
                                quantity     = total_deduct,
                                motive       = f'Combo "{prod.name}" — {mot}',
                                user_id      = current_user.id,
                                user_name    = current_user.display_name or current_user.username,
                            ))
                else:
                    prod.stock_quantity = max(0, prod.stock_quantity - int(qty))
                    db.session.add(StockMovement(
                        tenant_id    = tid(),
                        product_id   = prod.id,
                        product_name = prod.name,
                        type         = 'saida',
                        quantity     = int(qty),
                        motive       = mot,
                        user_id      = current_user.id,
                        user_name    = current_user.display_name or current_user.username,
                    ))

    db.session.commit()
    return jsonify({'sale_id': sale.id})

@sales_bp.route('/')
@login_required
def index():
    from datetime import date, datetime
    from app.models.cash import CashRegister

    from datetime import timedelta
    hoje = date.today()

    # Aceita período (de/ate); compatível com o parâmetro antigo 'data'
    data_legado = request.args.get('data')
    de_str  = request.args.get('de',  data_legado or hoje.isoformat())
    ate_str = request.args.get('ate', data_legado or hoje.isoformat())
    try:
        de_fil = date.fromisoformat(de_str)
    except ValueError:
        de_fil = hoje
    try:
        ate_fil = date.fromisoformat(ate_str)
    except ValueError:
        ate_fil = hoje
    # Garante ordem correta
    if de_fil > ate_fil:
        de_fil, ate_fil = ate_fil, de_fil

    inicio = datetime.combine(de_fil, datetime.min.time())
    fim    = datetime.combine(ate_fil, datetime.max.time())

    # Modo restrito: config ativa + caixa aberto por funcionário
    tenant = current_user.tenant
    cfg = tenant.get_settings()
    caixa = CashRegister.query.filter_by(tenant_id=tid(), status='open').first()
    modo_restrito = (
        cfg.get('dashboard_operador_restrito') and
        caixa is not None and
        caixa.operator_employee_id is not None
    )

    limite = 15 if modo_restrito else 1000

    sales = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.created_at >= inicio,
        Sale.created_at <= fim,
    ).order_by(Sale.created_at.desc()).limit(limite).all()

    total_periodo = sum(s.total for s in sales)
    periodo_um_dia = (de_fil == ate_fil)

    return render_template('sales/index.html',
        sales=sales,
        de_fil=de_fil,
        ate_fil=ate_fil,
        periodo_um_dia=periodo_um_dia,
        total_periodo=total_periodo,
        modo_restrito=modo_restrito,
        limite=limite,
        hoje=hoje.isoformat(),
        ontem=(hoje - timedelta(days=1)).isoformat(),
        inicio_mes=hoje.replace(day=1).isoformat(),
    )

@sales_bp.route('/<int:sale_id>')
@login_required
def detalhe(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    return render_template('sales/detalhe.html', sale=sale)

@sales_bp.route('/<int:sale_id>/comprovante')
@login_required
def comprovante(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    autoprint = request.args.get('autoprint', '0') == '1'
    store_name = current_user.tenant.store_name

    # monta mapa de componentes para combos
    combo_map = {}
    for item in sale.items:
        if item.product_id:
            ci_list = ComboItem.query.filter_by(combo_id=item.product_id).all()
            if ci_list:
                entries = []
                for ci in ci_list:
                    comp = Product.query.filter_by(id=ci.component_id, tenant_id=tid()).first()
                    if comp:
                        entries.append(type('C', (), {'name': comp.name, 'quantity': ci.quantity})())
                combo_map[item.product_id] = entries

    return render_template('sales/receipt.html',
        sale=sale,
        store_name=store_name,
        combo_map=combo_map,
        autoprint=autoprint,
    )

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
            combo_items = ComboItem.query.filter_by(combo_id=item.product_id).all()
            if combo_items:
                for ci in combo_items:
                    comp = Product.query.filter_by(id=ci.component_id, tenant_id=tid()).first()
                    if comp:
                        total = int(ci.quantity * item.quantity)
                        comp.stock_quantity += total
                        db.session.add(StockMovement(
                            tenant_id    = tid(),
                            product_id   = comp.id,
                            product_name = comp.name,
                            type         = 'entrada',
                            quantity     = total,
                            motive       = f'Cancelamento combo "{prod.name if prod else ""}" Venda #{sale.id}',
                            user_id      = current_user.id,
                            user_name    = current_user.display_name or current_user.username,
                        ))
            elif prod:
                prod.stock_quantity += int(item.quantity)
                db.session.add(StockMovement(
                    tenant_id    = tid(),
                    product_id   = prod.id,
                    product_name = prod.name,
                    type         = 'entrada',
                    quantity     = int(item.quantity),
                    motive       = f'Cancelamento Venda #{sale.id} — {motivo}',
                    user_id      = current_user.id,
                    user_name    = current_user.display_name or current_user.username,
                ))

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
