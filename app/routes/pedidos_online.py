from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
from app import db
from app.models.pedido_online import PedidoOnline
from app.models.sale import Sale, SaleItem
from app.models.product import Product
from app.models.cash import CashRegister
from app.models.stock import StockMovement
from app.models.combo import ComboItem
from datetime import datetime
import json

pedidos_online_bp = Blueprint('pedidos_online', __name__, url_prefix='/pedidos-online')


def tid():
    return current_user.tenant_id

def _user_id():
    # Funcionários (EmployeeLoginProxy, id "e_<n>") não estão na tabela users;
    # colunas FK->users recebem None. A autoria fica nos campos *_name.
    uid = current_user.id
    if isinstance(uid, str) and uid.startswith('e_'):
        return None
    return uid


@pedidos_online_bp.route('/')
@login_required
def index():
    pendentes = (PedidoOnline.query
                 .filter_by(tenant_id=tid(), status='pending')
                 .order_by(PedidoOnline.created_at.asc()).all())
    recentes  = (PedidoOnline.query
                 .filter(PedidoOnline.tenant_id == tid(),
                         PedidoOnline.status != 'pending')
                 .order_by(PedidoOnline.created_at.desc()).limit(50).all())
    return render_template('pedidos_online/index.html',
                           pendentes=pendentes, recentes=recentes)


@pedidos_online_bp.route('/<int:pedido_id>/aceitar', methods=['POST'])
@login_required
def aceitar(pedido_id):
    import traceback
    try:
        pedido = PedidoOnline.query.filter_by(id=pedido_id, tenant_id=tid()).first_or_404()
        if pedido.status != 'pending':
            return jsonify({'error': 'Pedido já processado.'}), 400

        uid = current_user.id
        if isinstance(uid, str) and uid.startswith('e_'):
            _emp_id = int(uid[2:])
            caixa = CashRegister.query.filter_by(tenant_id=tid(), status='open', operator_employee_id=_emp_id).first()
        else:
            from sqlalchemy import and_
            caixa = (CashRegister.query
                     .filter(CashRegister.tenant_id == tid(), CashRegister.status == 'open',
                             CashRegister.opened_by == uid, CashRegister.operator_employee_id == None)
                     .first()
                     or CashRegister.query.filter_by(tenant_id=tid(), status='open').first())
        cashier  = (caixa.operator_name if caixa and caixa.operator_name
                    else (current_user.display_name or current_user.username))
        items    = pedido.items

        # Cria venda
        sale = Sale(
            tenant_id      = tid(),
            customer_id    = None,
            delivery_mode  = 'entrega',
            delivery_fee   = pedido.taxa_entrega,
            subtotal       = pedido.subtotal,
            discount       = 0,
            discount_type  = None,
            total          = pedido.total,
            payment_method = pedido.payment_method,
            notes          = pedido.notes,
            source         = 'loja',
            cashier_name   = cashier,
            cash_register_id = caixa.id if caixa else None,
        )
        db.session.add(sale)
        db.session.flush()

        # Sequencial por tenant
        last = db.session.query(db.func.max(Sale.sale_number)).filter(
            Sale.tenant_id == tid(), Sale.id != sale.id
        ).scalar() or 0
        sale.sale_number = last + 1

        for i in items:
            qty  = float(i['quantity'])
            pid  = i.get('product_id')
            prod = Product.query.filter_by(id=pid, tenant_id=tid()).first() if pid else None
            # Preserva adicionais e observação do item no nome (SaleItem não tem
            # campo próprio) para aparecerem no recibo/cozinha.
            nome_item = i['name']
            addons_item = i.get('addons') or []
            if addons_item:
                nome_item += ' (+ ' + ', '.join(
                    a['name'] + (' x%d' % a['qty'] if a.get('qty', 1) > 1 else '')
                    for a in addons_item if a.get('name')) + ')'
            if i.get('notes'):
                nome_item += ' — ' + i['notes']
            nome_item = nome_item[:128]
            db.session.add(SaleItem(
                sale_id      = sale.id,
                product_id   = pid,
                product_name = nome_item,
                unit_price   = float(i['unit_price']),
                cost_price   = (prod.cost_price or 0) if prod else 0,
                quantity     = qty,
                total        = float(i['total']),
            ))
            if pid and prod:
                combo_items = ComboItem.query.filter_by(combo_id=pid).all()
                if combo_items:
                    for ci in combo_items:
                        comp = Product.query.filter_by(id=ci.component_id, tenant_id=tid()).first()
                        if comp:
                            deduct = int(ci.quantity * qty)
                            comp.stock_quantity = max(0, (comp.stock_quantity or 0) - deduct)
                            db.session.add(StockMovement(
                                tenant_id=tid(), product_id=comp.id, product_name=comp.name,
                                type='saida', quantity=deduct,
                                motive=f'Pedido Online #{pedido.id} — combo "{prod.name}"',
                                user_id=_user_id(),
                                user_name=current_user.display_name or current_user.username,
                            ))
                else:
                    prod.stock_quantity = max(0, (prod.stock_quantity or 0) - int(qty))
                    db.session.add(StockMovement(
                        tenant_id=tid(), product_id=prod.id, product_name=prod.name,
                        type='saida', quantity=int(qty),
                        motive=f'Pedido Online #{pedido.id}',
                        user_id=_user_id(),
                        user_name=current_user.display_name or current_user.username,
                    ))

        pedido.status      = 'accepted'
        pedido.accepted_at = datetime.now()
        pedido.sale_id     = sale.id
        db.session.commit()
        return jsonify({'ok': True, 'sale_id': sale.id})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Erro ao aceitar pedido {pedido_id}: {traceback.format_exc()}')
        return jsonify({'error': 'Erro interno ao processar o pedido. Tente novamente.'}), 500


@pedidos_online_bp.route('/<int:pedido_id>/recusar', methods=['POST'])
@login_required
def recusar(pedido_id):
    pedido = PedidoOnline.query.filter_by(id=pedido_id, tenant_id=tid()).first_or_404()
    if pedido.status != 'pending':
        return jsonify({'error': 'Pedido já processado.'}), 400
    data = request.get_json() or {}
    pedido.status        = 'rejected'
    pedido.rejected_at   = datetime.now()
    pedido.reject_reason = (data.get('reason') or 'Pedido recusado pela loja.').strip()
    db.session.commit()
    return jsonify({'ok': True})


# ── API: contagem de pendentes (para live-stats) ────────
@pedidos_online_bp.route('/api/pendentes')
@login_required
def api_pendentes():
    count = PedidoOnline.query.filter_by(tenant_id=tid(), status='pending').count()
    return jsonify({'count': count})
