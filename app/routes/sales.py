from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.sale import Sale, SaleItem
from app.models.sale_archive import SaleArchive
from app.models.product import Product
from app.models.customer import Customer
from app.models.cash import CashRegister
from app.models.stock import StockMovement
from app.models.combo import ComboItem
from app.auth_utils import autenticar_operador
import json as _json

sales_bp = Blueprint('sales', __name__, url_prefix='/vendas')


def _get_sale_or_archive(sale_id, tenant_id):
    """Busca venda ativa; se não achar, reconstrói a partir do arquivo."""
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tenant_id).first()
    if sale:
        return sale, False

    arq = SaleArchive.query.filter_by(original_id=sale_id, tenant_id=tenant_id).first()
    if not arq:
        return None, False

    # Reconstrói um objeto Sale-like com itens simulados a partir do JSON
    items_data = _json.loads(arq.items_json or '[]')
    fake_items = []
    for i in items_data:
        item = SaleItem.__new__(SaleItem)
        item.product_id   = i.get('product_id')
        item.product_name = i.get('product_name', '')
        item.unit_price   = i.get('unit_price', 0)
        item.cost_price   = i.get('cost_price', 0)
        item.quantity     = i.get('quantity', 1)
        item.total        = i.get('total', 0)
        fake_items.append(item)

    fake = Sale.__new__(Sale)
    fake.id               = arq.original_id
    fake.sale_number      = arq.sale_number
    fake.tenant_id        = arq.tenant_id
    fake.customer_id      = arq.customer_id
    fake.customer         = None
    fake.delivery_mode    = arq.delivery_mode or 'retirada'
    fake.delivery_fee     = arq.delivery_fee or 0
    fake.subtotal         = arq.subtotal or 0
    fake.total            = arq.total or 0
    fake.payment_method   = arq.payment_method or ''
    fake.payment_entries  = None
    fake.notes            = arq.notes
    fake.status           = arq.status
    fake.source           = arq.source
    fake.app_name         = arq.app_name
    fake.amount_paid      = arq.amount_paid
    fake.change_amount    = None
    fake.discount         = arq.discount or 0
    fake.discount_type    = arq.discount_type
    fake.cashier_name     = arq.cashier_name
    fake.cancelled_at     = arq.cancelled_at
    fake.cancelled_by_name= arq.cancelled_by_name
    fake.cancel_reason    = arq.cancel_reason
    fake.dispatched_at    = None
    fake.delivered_at     = None
    fake.motoboy_name     = None
    fake.employee_id      = arq.employee_id
    fake.created_at       = arq.created_at
    fake.items            = fake_items
    return fake, True  # True = veio do arquivo

def tid():
    return current_user.tenant_id

def _user_id():
    # Funcionários (EmployeeLoginProxy, id "e_<n>") não estão na tabela users;
    # colunas FK->users recebem None. A autoria fica nos campos *_name.
    uid = current_user.id
    if isinstance(uid, str) and uid.startswith('e_'):
        return None
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
    delivery_address = (data.get('delivery_address') or '').strip() or None
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
    combinado_tem_cartao = False
    if payment_entries_raw:
        payment_method       = 'combinado'
        payment_entries_json = _json.dumps(payment_entries_raw)
        amount_paid          = round(sum(float(e.get('amount', 0)) for e in payment_entries_raw), 2)
        _cards = ('cartao', 'credito', 'debito', 'cartao_credito', 'cartao_debito',
                  'entrega_cartao', 'entrega_cartao_credito', 'entrega_cartao_debito')
        combinado_tem_cartao = any(e.get('method') in _cards for e in payment_entries_raw)

    # Valida preço server-side — nunca confia no valor enviado pelo cliente
    _prod_cache = {}
    def _preco_servidor(item):
        pid = item.get('product_id')
        is_gelado = item.get('gelado', False)
        # Combinado usa preço de cartão só se alguma das formas for cartão
        is_cartao = (payment_method in ('cartao', 'credito', 'debito')
                     or (payment_method == 'combinado' and combinado_tem_cartao))
        if pid:
            if pid not in _prod_cache:
                _prod_cache[pid] = Product.query.filter_by(id=pid, tenant_id=tid()).first()
            p = _prod_cache[pid]
            if p:
                tenant = current_user.tenant
                if tenant and getattr(tenant, 'event_mode', False) and getattr(p, 'sale_price_event', 0):
                    return p.sale_price_event
                if is_gelado and getattr(p, 'sale_price_cold', 0):
                    if is_cartao and getattr(p, 'sale_price_cold_card', 0):
                        return p.sale_price_cold_card
                    return p.sale_price_cold
                if is_cartao and getattr(p, 'sale_price_card', 0):
                    return p.sale_price_card
                return p.sale_price
        # Produto sem ID (item avulso): aceita o preço do cliente
        return float(item.get('unit_price', 0))

    subtotal = sum(_preco_servidor(i) * float(i['quantity']) for i in items)

    if discount_type == 'percent':
        discount_input = min(discount_input, 100)  # teto de 100%
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
        delivery_address = delivery_address if delivery_mode == 'entrega' else None,
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

    # Sequencial por tenant
    last = db.session.query(db.func.max(Sale.sale_number)).filter(
        Sale.tenant_id == tid(), Sale.id != sale.id
    ).scalar() or 0
    sale.sale_number = last + 1

    for i in items:
        qty = float(i['quantity'])
        pid = i.get('product_id') or None
        prod = _prod_cache.get(pid) if pid else None
        if pid and prod is None:
            prod = Product.query.filter_by(id=pid, tenant_id=tid()).first()
        unit_price_srv = _preco_servidor(i)
        item = SaleItem(
            sale_id      = sale.id,
            product_id   = pid,
            product_name = i['name'],
            unit_price   = unit_price_srv,
            cost_price   = (prod.cost_price or 0) if prod else 0,
            quantity     = qty,
            total        = unit_price_srv * qty,
        )
        db.session.add(item)

        # desconta estoque e registra movimentação
        if pid:
            if not prod:
                prod = Product.query.filter_by(id=pid, tenant_id=tid()).first()
            if prod:
                mot = f'Venda App #{sale.sale_number or sale.id} ({app_name})' if source == 'app' and app_name else f'Venda #{sale.sale_number or sale.id}'
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
                elif prod.pack_parent_id and prod.pack_qty:
                    # Pack: deduz do produto pai
                    parent = Product.query.filter_by(id=prod.pack_parent_id, tenant_id=tid()).first()
                    if parent:
                        total_deduct = int(prod.pack_qty * qty)
                        parent.stock_quantity = max(0, parent.stock_quantity - total_deduct)
                        db.session.add(StockMovement(
                            tenant_id    = tid(),
                            product_id   = parent.id,
                            product_name = parent.name,
                            type         = 'saida',
                            quantity     = total_deduct,
                            motive       = f'Pack "{prod.name}" ({prod.pack_qty}un) — {mot}',
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
                notes       = f'Venda #{sale.sale_number or sale.id} — PDV',
                sale_id     = sale.id,
            )
            db.session.add(vale)
            db.session.commit()

    return jsonify({'sale_id': sale.id})

@sales_bp.route('/')
@login_required
def index():
    from datetime import date, datetime, time

    from datetime import timedelta
    from app.models.cash import CashRegister
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

    # Horários opcionais (para caixa que atravessa a madrugada). Formato "HH:MM".
    hora_de  = request.args.get('hora_de', '').strip()
    hora_ate = request.args.get('hora_ate', '').strip()
    def _parse_hora(s, hfim=False):
        try:
            h, m = s.split(':')
            return time(int(h), int(m), 59 if hfim else 0)
        except Exception:
            return None
    t_de  = _parse_hora(hora_de) or datetime.min.time()
    t_ate = _parse_hora(hora_ate, hfim=True) or datetime.max.time()

    inicio = datetime.combine(de_fil, t_de)
    fim    = datetime.combine(ate_fil, t_ate)

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

    # Busca por número do pedido — ignora o filtro de data (vale também no modo operador).
    # Casa com o que a tela mostra (#sale_number, ou #id quando a venda não tem número).
    busca_pedido = request.args.get('pedido', '').strip()
    if busca_pedido:
        from sqlalchemy import or_, and_
        num = int(busca_pedido) if busca_pedido.isdigit() else None
        sales = Sale.query.filter(
            Sale.tenant_id == tid(),
            Sale.status == 'confirmed',
            or_(Sale.sale_number == num,
                and_(Sale.sale_number == None, Sale.id == num)),
        ).all() if num is not None else []
    else:
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
        hora_de=hora_de,
        hora_ate=hora_ate,
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
    sale, arquivada = _get_sale_or_archive(sale_id, tid())
    if not sale:
        from flask import abort; abort(404)
    return render_template('sales/detalhe.html', sale=sale, arquivada=arquivada)

@sales_bp.route('/<int:sale_id>/comprovante')
@login_required
def comprovante(sale_id):
    sale, _ = _get_sale_or_archive(sale_id, tid())
    if not sale:
        from flask import abort; abort(404)
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

    from app.models.pedido_online import PedidoOnline
    pedido_online = PedidoOnline.query.filter_by(sale_id=sale_id, tenant_id=tid()).first()

    return render_template('sales/receipt.html',
        sale=sale,
        store_name=store_name,
        combo_map=combo_map,
        autoprint=autoprint,
        payment_entries=payment_entries,
        pedido_online=pedido_online,
    )

@sales_bp.route('/<int:sale_id>/escpos')
@login_required
def escpos(sale_id):
    import base64
    from app.models.pedido_online import PedidoOnline
    sale, _ = _get_sale_or_archive(sale_id, tid())
    if not sale:
        from flask import abort; abort(404)
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
        d += CENTER + BIG + enc(f'PEDIDO #{sale.sale_number or sale.id}'.center(W // 2)) + NORM + NL
        d += ctr(f'{date_str}  |  {time_str}')
        d += sep('=')
        return d

    def itens_com_combo():
        d  = LEFT + enc('PRODUTO'.ljust(W-20) + 'QTD'.center(8) + 'TOTAL'.rjust(12)) + NL
        d += sep()
        def _wrap_words(text, width):
            """Quebra texto em linhas respeitando palavras inteiras."""
            words, lines, cur = text.split(), [], ''
            for w in words:
                if cur and len(cur) + 1 + len(w) > width:
                    lines.append(cur)
                    cur = w
                else:
                    cur = (cur + ' ' + w).strip()
            if cur:
                lines.append(cur)
            return lines or ['']

        for item in sale.items:
            full_nm = item.product_name
            col_nm  = W - 20
            linhas_nm = _wrap_words(full_nm, col_nm)
            # primeira linha: nome + qtd + total
            d += LEFT + enc(linhas_nm[0].ljust(col_nm) + str(int(item.quantity)).center(8) + f'R${item.total:.2f}'.rjust(12)) + NL
            # linhas seguintes (se nome longo)
            for extra in linhas_nm[1:]:
                d += LEFT + enc(extra) + NL
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
                # Suporta formato novo "rua - num - comp - bairro - REF: x"
                # e formato legado "Rua: x | Número: y | ..."
                if ' | ' in cli_end:
                    partes = [p.strip() for p in cli_end.split(' | ') if p.strip()]
                else:
                    partes = [p.strip() for p in cli_end.split(' - ') if p.strip()]
                labels = ['Rua:', 'Número:', 'Complemento:', 'Bairro:', 'Referência:']
                # formato legado já vem com label; formato novo não tem
                if partes and not any(partes[0].startswith(lb) for lb in labels):
                    rotulos = ['Rua:', 'Número:', 'Complemento:', 'Bairro:', 'Referência:']
                    for idx2, parte in enumerate(partes):
                        rot = rotulos[idx2] if idx2 < len(rotulos) else ''
                        if rot == 'Referência:' or parte.startswith('REF:'):
                            d += lft(f'Referencia: {parte.replace("REF:", "").strip()}')
                        elif rot:
                            d += lft(f'{rot} {parte}')
                        else:
                            d += lft(parte)
                else:
                    for parte in partes:
                        d += lft(parte)
            elif sale.customer:
                c = sale.customer
                rua    = c.address or ''
                num    = getattr(c, 'address_number', None) or ''
                ref    = getattr(c, 'address_ref', None) or ''
                bairro = c.bairro or (c.neighborhood.name if c.neighborhood else '')
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
    if sale.payment_method == 'combinado':
        data += cols('Pagamento', sale.payment_label)  # ex.: Credito + Pix
        for e in sale.payment_entries_list:
            lbl = pgto_map.get(e.get('method'), e.get('method') or '')
            data += cols(f'  {lbl}', f'R${float(e.get("amount", 0)):.2f}')
    else:
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
                            motive       = f'Cancelamento combo "{prod.name if prod else ""}" Venda #{sale.sale_number or sale.id}',
                            user_id      = _user_id(),
                            user_name    = current_user.display_name or current_user.username,
                        ))
            elif prod and prod.pack_parent_id and prod.pack_qty:
                parent = Product.query.filter_by(id=prod.pack_parent_id, tenant_id=tid()).first()
                if parent:
                    total = int(prod.pack_qty * item.quantity)
                    parent.stock_quantity += total
                    db.session.add(StockMovement(
                        tenant_id    = tid(),
                        product_id   = parent.id,
                        product_name = parent.name,
                        type         = 'entrada',
                        quantity     = total,
                        motive       = f'Cancelamento pack "{prod.name}" Venda #{sale.sale_number or sale.id}',
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
                    motive       = f'Cancelamento Venda #{sale.sale_number or sale.id} — {motivo}',
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


@sales_bp.route('/auditoria-descontos')
@login_required
def auditoria_descontos():
    filtro_de  = request.args.get('de', '')
    filtro_ate = request.args.get('ate', '')

    query = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status != 'cancelled',
        Sale.discount > 0,
    )

    if filtro_de:
        try:
            query = query.filter(Sale.created_at >= filtro_de)
        except Exception:
            pass
    if filtro_ate:
        try:
            query = query.filter(db.func.date(Sale.created_at) <= filtro_ate)
        except Exception:
            pass

    vendas = query.order_by(Sale.created_at.desc()).all()
    total_desconto = sum(v.discount or 0 for v in vendas)
    total_vendido  = sum(v.total for v in vendas)

    return render_template('sales/auditoria_descontos.html',
        vendas=vendas, total_desconto=total_desconto, total_vendido=total_vendido,
        filtro_de=filtro_de, filtro_ate=filtro_ate)
