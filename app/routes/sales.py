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

def _user_id():
    uid = current_user.id
    if isinstance(uid, str) and uid.startswith('e_'):
        return int(uid[2:])
    return uid

def _caixa_aberto():
    return CashRegister.query.filter_by(tenant_id=tid(), status='open').first()

@sales_bp.route('/nova')
@login_required
def nova():
    if not _caixa_aberto():
        flash('Abra o caixa antes de realizar uma venda.', 'warning')
        return redirect(url_for('cash.index'))
    from app.models.tenant import Tenant
    tenant = Tenant.query.get(tid())
    event_mode = tenant.event_mode if tenant else False
    evento_visivel = tenant.get_settings().get('modo_evento_visivel', False) if tenant else False
    return render_template('sales/nova.html', event_mode=event_mode, evento_visivel=evento_visivel)

@sales_bp.route('/confirmar', methods=['POST'])
@login_required
def confirmar():
    if not _caixa_aberto():
        return jsonify({'error': 'Caixa fechado. Abra o caixa antes de realizar uma venda.'}), 403

    data = request.get_json()
    if not data or not data.get('items'):
        return jsonify({'error': 'Carrinho vazio'}), 400

    import json as _json
    customer_id    = data.get('customer_id') or None
    delivery_mode  = data.get('delivery_mode', 'retirada')
    delivery_fee   = float(data.get('delivery_fee', 0))
    payment_method = data.get('payment_method', 'dinheiro')
    notes          = data.get('notes', '')
    source         = data.get('source', 'loja')
    app_name       = data.get('app_name', '') if source == 'app' else None
    amount_paid    = float(data.get('amount_paid', 0) or 0) or None
    employee_id    = data.get('employee_id') or None
    items          = data.get('items', [])
    discount_type  = data.get('discount_type') or None   # 'value' | 'percent' | None
    discount_input = float(data.get('discount', 0) or 0)

    # Pagamento combinado
    payment_entries_raw  = data.get('payment_entries') or []
    payment_entries_json = None
    if payment_entries_raw:
        payment_method       = 'combinado'
        payment_entries_json = _json.dumps(payment_entries_raw)
        amount_paid          = round(sum(float(e.get('amount', 0)) for e in payment_entries_raw), 2)

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
        amount_paid      = amount_paid,
        change_amount    = round(amount_paid - total, 2) if amount_paid and amount_paid > total else None,
        cashier_name     = cashier,
        payment_entries  = payment_entries_json,
        employee_id      = int(employee_id) if employee_id else None,
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
                                user_id      = _user_id(),
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
                        user_id      = _user_id(),
                        user_name    = current_user.display_name or current_user.username,
                    ))

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        from flask import current_app
        current_app.logger.error(f'[confirmar_venda] {e}')
        return jsonify({'error': str(e)}), 500

    # Se pagamento funcionário, lança vale automaticamente
    if payment_method == 'funcionario' and employee_id:
        from app.models.vale import Vale
        from datetime import date as _date
        emp = __import__('app.models.vale', fromlist=['Employee']).Employee.query.filter_by(
            id=int(employee_id), tenant_id=tid()).first()
        if emp:
            vale = Vale(
                tenant_id   = tid(),
                employee_id = emp.id,
                amount      = total,
                date        = _date.today(),
                notes       = f'Venda #{sale.id} — PDV',
                sale_id     = sale.id,
            )
            db.session.add(vale)
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

    # Busca por número do pedido — ignora o filtro de data
    busca_pedido = request.args.get('pedido', '').strip()
    if busca_pedido and not modo_restrito:
        sales = Sale.query.filter(
            Sale.tenant_id == tid(),
            Sale.status == 'confirmed',
            Sale.id == int(busca_pedido),
        ).all() if busca_pedido.isdigit() else []
    else:
        busca_pedido = ''
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
        busca_pedido=busca_pedido,
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

    import json as _json
    payment_entries = []
    if sale.payment_method == 'combinado' and sale.payment_entries:
        try:
            payment_entries = _json.loads(sale.payment_entries)
        except Exception:
            pass

    return render_template('sales/receipt.html',
        sale=sale,
        store_name=store_name,
        combo_map=combo_map,
        autoprint=autoprint,
        payment_entries=payment_entries,
    )

@sales_bp.route('/<int:sale_id>/escpos')
@login_required
def escpos(sale_id):
    import base64
    from app.models.pedido_online import PedidoOnline
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    store_name = current_user.tenant.store_name or 'Vendix'

    # Dados do cliente — pode vir do cadastro ou do pedido online
    pedido_online = PedidoOnline.query.filter_by(sale_id=sale_id, tenant_id=tid()).first()
    cli_nome  = (sale.customer.name  if sale.customer else None) or (pedido_online.cliente_nome if pedido_online else None)
    cli_tel   = (sale.customer.phone if sale.customer else None) or (pedido_online.cliente_tel  if pedido_online else None)
    cli_end   = pedido_online.endereco if pedido_online else None

    # Monta mapa de composição para combos
    combo_map = {}
    for item in sale.items:
        if item.product_id:
            ci_list = ComboItem.query.filter_by(combo_id=item.product_id).all()
            if ci_list:
                combo_map[item.product_id] = ci_list

    W = 42
    INIT   = b'\x1b@'
    CP850  = b'\x1bt\x02'   # seleciona code page PC850 (suporte a ã õ ç etc.)
    CENTER = b'\x1ba\x01'
    LEFT   = b'\x1ba\x00'
    BON    = b'\x1bE\x01'
    BIG    = b'\x1d!\x11'
    NORM   = b'\x1d!\x00'
    CUT    = b'\x1dV\x01'
    NL     = b'\n'

    def enc(s):  return s.encode('cp850', errors='replace')
    def ctr(s):  return CENTER + enc(s[:W].center(W)) + NL
    def lft(s):  return LEFT   + enc(s[:W]) + NL
    def cols(l, r):
        r = str(r); l = str(l)[:W - len(r) - 1]
        return LEFT + enc(l.ljust(W - len(r)) + r) + NL
    def sep(c='-'): return LEFT + enc(c * W) + NL

    def cabecalho():
        d  = INIT + CP850 + BON
        d += CENTER + enc(parts[0].upper().center(W)) + NL
        if len(parts) > 1:
            d += ctr(f'* {parts[1].upper()} *')
        d += sep('=')
        d += CENTER + BIG + enc(f'PEDIDO #{sale.id}'.center(W // 2)) + NORM + NL
        d += ctr(f'{date_str}  |  {time_str}')
        d += sep('=')
        return d

    def itens_com_combo():
        d  = LEFT + enc('PRODUTO'.ljust(W-20) + 'QTD'.center(8) + 'TOTAL'.rjust(12)) + NL
        d += sep()
        for item in sale.items:
            nm = item.product_name[:W-20]
            d += LEFT + enc(nm.ljust(W-20) + str(int(item.quantity)).center(8) + f'R${item.total:.2f}'.rjust(12)) + NL
            # Composição do combo
            if item.product_id and item.product_id in combo_map:
                for ci in combo_map[item.product_id]:
                    comp_name = f'  - {ci.component.name}'[:W-6]
                    comp_qty  = f'{int(ci.quantity * item.quantity)}x'.rjust(6)
                    d += LEFT + enc(comp_name.ljust(W-6) + comp_qty) + NL
        d += sep()
        return d

    def bloco_cliente():
        """Monta bloco nome + endereço + telefone para as duas vias."""
        d = b''
        if not cli_nome and not cli_end:
            return d
        if cli_nome:
            d += lft(f'Cliente: {cli_nome}')
        if sale.delivery_mode == 'entrega':
            if cli_end:
                # Pedido online: formato "Rua: X | Número: Y | Bairro: Z | ..."
                for parte in cli_end.split(' | '):
                    if parte.strip():
                        d += lft(parte.strip())
            elif sale.customer:
                c = sale.customer
                rua    = c.address or ''
                num    = getattr(c, 'address_number', None) or ''
                ref    = getattr(c, 'address_ref', None) or ''
                bairro = c.neighborhood.name if c.neighborhood else ''
                if rua or num:
                    d += lft(f'End: {rua}{"  n° " + num if num else ""}')
                if bairro:
                    d += lft(f'Bairro: {bairro}')
                if ref:
                    d += lft(f'Ref: {ref}')
            if cli_tel:
                d += lft(f'Tel: {cli_tel}')
        return d

    parts    = store_name.split(' ', 1)
    dt       = sale.created_at
    date_str = dt.strftime('%d/%m/%Y') if dt else ''
    time_str = dt.strftime('%H:%M')    if dt else ''

    pgto_map = {
        'dinheiro':'Dinheiro','cartao_credito':'Credito','cartao_debito':'Debito',
        'pix':'Pix','conta':'Conta','funcionario':'Funcionario',
        'entrega_dinheiro':'Dinheiro','entrega_pix':'Pix',
        'entrega_cartao_credito':'Credito','entrega_cartao_debito':'Debito',
        'combinado':'Combinado',
    }

    # ── VIA 1: CAIXA (itens + pagamento) ─────────────────────────────────────
    data  = cabecalho()
    bloco = bloco_cliente()
    if bloco:
        data += bloco
        data += sep()
    data += itens_com_combo()
    data += cols('Subtotal', f'R${sale.subtotal:.2f}')
    if sale.delivery_fee and sale.delivery_fee > 0:
        data += cols('Taxa Entrega', f'R${sale.delivery_fee:.2f}')
    if sale.discount and sale.discount > 0:
        data += cols('Desconto', f'-R${sale.discount:.2f}')
    data += sep('=')
    data += LEFT + enc('TOTAL'.ljust(W-12) + f'R${sale.total:.2f}'.rjust(12)) + NL
    data += sep('=')
    data += cols('Pagamento', pgto_map.get(sale.payment_method, sale.payment_method))
    if sale.payment_method in ('dinheiro','entrega_dinheiro') and sale.amount_paid:
        data += cols('  Recebido', f'R${sale.amount_paid:.2f}')
    if sale.change_amount and sale.change_amount > 0:
        data += cols('  Troco', f'R${sale.change_amount:.2f}')
    if sale.notes:
        data += sep()
        data += lft(f'Obs: {sale.notes}')
    data += sep()
    data += ctr('Obrigado pela preferencia!')
    data += ctr('Volte sempre!')
    data += NL * 4
    data += CUT

    # ── VIA 2: CLIENTE (somente itens) ───────────────────────────────────────
    data += cabecalho()
    if bloco:
        data += bloco
        data += sep()
    data += itens_com_combo()
    if sale.notes:
        data += lft(f'Obs: {sale.notes}')
        data += sep()
    data += ctr('Obrigado pela preferencia!')
    data += NL * 4
    data += CUT

    from flask import Response
    return Response(data, mimetype='application/octet-stream')


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
    sale.cancelled_by_id = _user_id()
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
                            user_id      = _user_id(),
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
                    user_id      = _user_id(),
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
