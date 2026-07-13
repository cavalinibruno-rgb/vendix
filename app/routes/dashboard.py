from flask import Blueprint, render_template, request, redirect, url_for, session
from flask_login import login_required, current_user
from app import db
from app.models.tenant import Tenant
from app.models.sale import Sale
from app.models.cash import CashRegister
from app.models.user import User
from datetime import datetime, date, timedelta

dashboard_bp = Blueprint('dashboard', __name__)

def require_active_tenant(f):
    from functools import wraps
    from flask import redirect, url_for, flash
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.is_master:
            return f(*args, **kwargs)
        tenant = Tenant.query.get(current_user.tenant_id)
        if not tenant or not tenant.is_active:
            flash('Sua assinatura está suspensa.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

@dashboard_bp.route('/dashboard')
@login_required
@require_active_tenant
def index():
    tenant = Tenant.query.get(current_user.tenant_id)
    tid = current_user.tenant_id

    hoje_inicio = datetime.combine(date.today(), datetime.min.time())

    todas_hoje = Sale.query.filter(
        Sale.tenant_id == tid,
        Sale.status == 'confirmed',
        Sale.created_at >= hoje_inicio,
    ).all()

    def entra_no_caixa(v):
        if v.source == 'loja' or v.source is None:
            return True
        return v.payment_method in ('entrega_dinheiro', 'entrega_cartao', 'entrega_cartao_credito', 'entrega_cartao_debito', 'entrega_pix')

    vendas_hoje = [v for v in todas_hoje if entra_no_caixa(v)]

    total_dinheiro = sum(v.total for v in vendas_hoje if v.payment_method in ('dinheiro', 'entrega_dinheiro'))
    total_credito     = sum(v.total for v in vendas_hoje if v.payment_method in ('cartao_credito', 'entrega_cartao_credito', 'cartao', 'entrega_cartao'))
    total_debito      = sum(v.total for v in vendas_hoje if v.payment_method in ('cartao_debito', 'entrega_cartao_debito'))
    total_cartao      = total_credito + total_debito
    total_pix         = sum(v.total for v in vendas_hoje if v.payment_method in ('pix', 'entrega_pix'))
    total_conta       = sum(v.total for v in vendas_hoje if v.payment_method == 'conta')
    total_funcionario = sum(v.total for v in vendas_hoje if v.payment_method == 'funcionario')
    total_geral       = sum(v.total for v in vendas_hoje)

    # Ticket médio do dia
    ticket_dia = (total_geral / len(vendas_hoje)) if vendas_hoje else 0

    # Ticket médio mensal (mês atual) — usa aggregate no banco
    from sqlalchemy import func as sa_func
    mes_inicio = datetime.combine(date.today().replace(day=1), datetime.min.time())
    _agg_mes = db.session.query(
        sa_func.avg(Sale.total)
    ).filter(
        Sale.tenant_id == tid,
        Sale.status == 'confirmed',
        Sale.created_at >= mes_inicio,
    ).first()
    ticket_mensal = float(_agg_mes[0] or 0)

    # Ticket médio geral (todos os tempos) — usa aggregate no banco
    _agg = db.session.query(
        sa_func.avg(Sale.total)
    ).filter_by(tenant_id=tid, status='confirmed').first()
    ticket_geral = float(_agg[0] or 0)

    uid = current_user.id
    if isinstance(uid, str) and uid.startswith('e_'):
        # Operador: vê apenas o próprio caixa
        emp_id = int(uid[2:])
        caixa = CashRegister.query.filter_by(
            tenant_id=tid, status='open', operator_employee_id=emp_id
        ).first()
        caixas_abertos = [caixa] if caixa else []
    else:
        # Dono: vê todos os caixas abertos da loja
        caixas_abertos = CashRegister.query.filter_by(
            tenant_id=tid, status='open'
        ).order_by(CashRegister.opened_at).all()
        caixa = caixas_abertos[0] if caixas_abertos else None

    ultimas_vendas = Sale.query.filter_by(tenant_id=tid, status='confirmed')\
                               .order_by(Sale.created_at.desc()).limit(10).all()

    # Produtos com estoque baixo ou zerado (exclui combos)
    from app.models.product import Product
    from app.models.combo import ComboItem
    combo_ids = db.session.query(ComboItem.combo_id).distinct()
    produtos_tenant = Product.query.filter_by(tenant_id=tid, active=True)\
        .filter(~Product.id.in_(combo_ids))\
        .filter(Product.stock_quantity <= Product.min_stock).all()

    # Mapa de estoque dos pais para calcular estoque efetivo dos packs
    parent_ids = {p.pack_parent_id for p in produtos_tenant if p.pack_parent_id}
    parent_stock_map = {}
    parent_min_map   = {}
    if parent_ids:
        for pr in Product.query.filter(Product.id.in_(parent_ids)).with_entities(
                Product.id, Product.stock_quantity, Product.min_stock).all():
            parent_stock_map[pr.id] = pr.stock_quantity
            parent_min_map[pr.id]   = pr.min_stock

    def _eff_stock(p):
        if p.pack_parent_id and p.pack_qty:
            return parent_stock_map.get(p.pack_parent_id, 0) // p.pack_qty
        return p.stock_quantity

    def _eff_min(p):
        if p.pack_parent_id and p.pack_qty:
            return parent_min_map.get(p.pack_parent_id, 0) // p.pack_qty
        return p.min_stock

    estoque_baixo = [
        p for p in produtos_tenant
        if not p.combo_items and _eff_stock(p) <= _eff_min(p)
    ]
    estoque_baixo.sort(key=lambda p: _eff_stock(p))

    cfg = tenant.get_settings()
    modo_restrito = (
        cfg.get('dashboard_operador_restrito') and
        current_user.is_employee and
        caixa is not None and
        caixa.operator_employee_id is not None
    )

    # Quando caixa fechado, exige senha do dono para ver valores
    desbloqueado = caixa is not None or session.get('dashboard_desbloqueado', False)
    senha_erro = session.pop('dashboard_erro', False)

    return render_template('dashboard/index.html',
        tenant=tenant,
        qtd_vendas=len(vendas_hoje),
        total_dinheiro=total_dinheiro,
        total_credito=total_credito, total_debito=total_debito,
        total_cartao=total_cartao,
        total_pix=total_pix,
        total_conta=total_conta,
        total_funcionario=total_funcionario,
        total_geral=total_geral,
        caixa=caixa,
        caixas_abertos=caixas_abertos,
        ultimas_vendas=ultimas_vendas,
        estoque_baixo=estoque_baixo,
        eff_stock=_eff_stock, eff_min=_eff_min,
        modo_restrito=modo_restrito,
        desbloqueado=desbloqueado,
        senha_erro=senha_erro,
        ticket_dia=ticket_dia,
        ticket_mensal=ticket_mensal,
        ticket_geral=ticket_geral,
        event_mode=tenant.event_mode if tenant else False,
        evento_visivel=tenant.get_settings().get('modo_evento_visivel', False) if tenant else False,
    )

@dashboard_bp.route('/dashboard/desbloquear', methods=['POST'])
@login_required
def desbloquear():
    senha = request.form.get('senha', '')
    user = None if current_user.is_employee else User.query.get(current_user.id)
    if user and user.check_password(senha):
        session['dashboard_desbloqueado'] = True
    else:
        session['dashboard_desbloqueado'] = False
        session['dashboard_erro'] = True
    return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/dashboard/evento/toggle', methods=['POST'])
@login_required
def evento_toggle():
    from app import db
    from app.auth_utils import autenticar_operador
    op_username = request.form.get('op_username', '').strip()
    op_password = request.form.get('op_password', '').strip()
    _, ok = autenticar_operador(current_user.tenant_id, op_username, op_password)
    if not ok:
        return redirect(url_for('dashboard.index', evento_erro=1))
    tenant = Tenant.query.get(current_user.tenant_id)
    if tenant:
        tenant.event_mode = not tenant.event_mode
        db.session.commit()
    return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/api/event-mode')
@login_required
def api_event_mode():
    from flask import jsonify
    tenant = Tenant.query.get(current_user.tenant_id)
    return jsonify({'event_mode': tenant.event_mode if tenant else False})

@dashboard_bp.route('/dashboard/bloquear')
@login_required
def bloquear():
    session.pop('dashboard_desbloqueado', None)
    return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/api/live-stats')
@login_required
def live_stats():
    from flask import jsonify
    tid = current_user.tenant_id
    hoje_inicio = datetime.combine(date.today(), datetime.min.time())

    # Conta e soma as vendas do caixa direto no banco (COUNT/SUM) em vez de
    # carregar todas as vendas do dia pra memoria. Mesmo criterio do entra_no_caixa:
    # source='loja' OU source nulo OU pagamento de entrega.
    from sqlalchemy import func as sa_func, or_
    _cx = db.session.query(
        sa_func.count(Sale.id),
        sa_func.coalesce(sa_func.sum(Sale.total), 0.0),
    ).filter(
        Sale.tenant_id == tid,
        Sale.status == 'confirmed',
        Sale.created_at >= hoje_inicio,
        or_(
            Sale.source == 'loja',
            Sale.source.is_(None),
            Sale.payment_method.in_(('entrega_dinheiro', 'entrega_cartao', 'entrega_pix')),
        ),
    ).first()
    qtd_vendas   = _cx[0] or 0
    total_geral  = float(_cx[1] or 0)

    # Entregas
    base = Sale.query.filter_by(tenant_id=tid, status='confirmed', delivery_mode='entrega')
    entregas_pendentes = base.filter(Sale.dispatched_at == None).count()
    entregas_retorno   = base.filter(Sale.dispatched_at != None, Sale.delivered_at == None).count()

    # Última venda para detectar "nova venda"
    ultima = Sale.query.filter_by(tenant_id=tid, status='confirmed') \
                       .order_by(Sale.created_at.desc()).first()

    # Pedidos online pendentes
    from app.models.pedido_online import PedidoOnline
    pedidos_pendentes = PedidoOnline.query.filter_by(tenant_id=tid, status='pending').count()
    ultimo_pedido     = PedidoOnline.query.filter_by(tenant_id=tid, status='pending') \
                                          .order_by(PedidoOnline.created_at.desc()).first()

    return jsonify({
        'qtd_vendas':           qtd_vendas,
        'total_geral':          total_geral,
        'entregas_pendentes':   entregas_pendentes,
        'entregas_retorno':     entregas_retorno,
        'ultima_venda_id':      ultima.id if ultima else None,
        'ultima_venda_total':   ultima.total if ultima else 0,
        'ultima_venda_cliente': (ultima.customer.name if ultima and ultima.customer else 'Consumidor') if ultima else '',
        'pedidos_pendentes':     pedidos_pendentes,
        'ultimo_pedido_id':      ultimo_pedido.id if ultimo_pedido else None,
        'ultimo_pedido_nome':    ultimo_pedido.cliente_nome if ultimo_pedido else '',
        'ultimo_pedido_tel':     ultimo_pedido.cliente_tel if ultimo_pedido else '',
        'ultimo_pedido_end':     (
            (ultimo_pedido.endereco or '') +
            (' — ' + ultimo_pedido.bairro_nome if ultimo_pedido and ultimo_pedido.bairro_nome else '')
        ) if ultimo_pedido else '',
        'ultimo_pedido_total':   ultimo_pedido.total if ultimo_pedido else 0,
        'ultimo_pedido_itens':   ultimo_pedido.items if ultimo_pedido else [],
        'ultimo_pedido_pgto':    ultimo_pedido.payment_method if ultimo_pedido else '',
    })
