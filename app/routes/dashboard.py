from flask import Blueprint, render_template, request, redirect, url_for, session
from flask_login import login_required, current_user
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

@dashboard_bp.route('/')
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
        return v.payment_method in ('entrega_dinheiro', 'entrega_cartao', 'entrega_pix')

    vendas_hoje = [v for v in todas_hoje if entra_no_caixa(v)]

    total_dinheiro = sum(v.total for v in vendas_hoje if v.payment_method in ('dinheiro', 'entrega_dinheiro'))
    total_cartao   = sum(v.total for v in vendas_hoje if v.payment_method in ('cartao', 'entrega_cartao'))
    total_pix      = sum(v.total for v in vendas_hoje if v.payment_method in ('pix', 'entrega_pix'))
    total_conta    = sum(v.total for v in vendas_hoje if v.payment_method == 'conta')
    total_geral    = sum(v.total for v in vendas_hoje)

    # Ticket médio do dia
    ticket_dia = (total_geral / len(vendas_hoje)) if vendas_hoje else 0

    # Ticket médio mensal (mês atual)
    mes_inicio = datetime.combine(date.today().replace(day=1), datetime.min.time())
    vendas_mes = Sale.query.filter(
        Sale.tenant_id == tid,
        Sale.status == 'confirmed',
        Sale.created_at >= mes_inicio,
    ).all()
    ticket_mensal = (sum(v.total for v in vendas_mes) / len(vendas_mes)) if vendas_mes else 0

    # Ticket médio geral (todos os tempos)
    todas_vendas = Sale.query.filter_by(tenant_id=tid, status='confirmed').all()
    ticket_geral = (sum(v.total for v in todas_vendas) / len(todas_vendas)) if todas_vendas else 0

    caixa = CashRegister.query.filter_by(tenant_id=tid, status='open').first()

    ultimas_vendas = Sale.query.filter_by(tenant_id=tid, status='confirmed')\
                               .order_by(Sale.created_at.desc()).limit(10).all()

    # Produtos com estoque baixo ou zerado (exclui combos, que não têm estoque próprio)
    from app.models.product import Product
    produtos_tenant = Product.query.filter_by(tenant_id=tid, active=True).all()
    estoque_baixo = [
        p for p in produtos_tenant
        if not p.combo_items and p.stock_quantity <= p.min_stock
    ]
    estoque_baixo.sort(key=lambda p: p.stock_quantity)

    cfg = tenant.get_settings()
    modo_restrito = (
        cfg.get('dashboard_operador_restrito') and
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
        total_cartao=total_cartao,
        total_pix=total_pix,
        total_conta=total_conta,
        total_geral=total_geral,
        caixa=caixa,
        ultimas_vendas=ultimas_vendas,
        estoque_baixo=estoque_baixo,
        modo_restrito=modo_restrito,
        desbloqueado=desbloqueado,
        senha_erro=senha_erro,
        ticket_dia=ticket_dia,
        ticket_mensal=ticket_mensal,
        ticket_geral=ticket_geral,
    )

@dashboard_bp.route('/dashboard/desbloquear', methods=['POST'])
@login_required
def desbloquear():
    senha = request.form.get('senha', '')
    user = User.query.get(current_user.id)
    if user and user.check_password(senha):
        session['dashboard_desbloqueado'] = True
    else:
        session['dashboard_desbloqueado'] = False
        session['dashboard_erro'] = True
    return redirect(url_for('dashboard.index'))

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

    vendas_hoje = Sale.query.filter(
        Sale.tenant_id == tid,
        Sale.status == 'confirmed',
        Sale.created_at >= hoje_inicio,
    ).all()

    def entra_no_caixa(v):
        return v.source in ('loja', None) or v.payment_method in ('entrega_dinheiro', 'entrega_cartao', 'entrega_pix')

    vendas_caixa = [v for v in vendas_hoje if entra_no_caixa(v)]
    total_geral  = sum(v.total for v in vendas_caixa)

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
        'qtd_vendas':           len(vendas_caixa),
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
