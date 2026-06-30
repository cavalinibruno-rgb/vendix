from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from collections import defaultdict
from app import db
from app.models.sale import Sale
from app.models.motoboy import Motoboy
from app.models.pedido_online import PedidoOnline

despacho_bp = Blueprint('entregas', __name__, url_prefix='/entregas')

def tid():
    return current_user.tenant_id

@despacho_bp.route('/')
@login_required
def index():
    base = Sale.query.filter_by(tenant_id=tid(), status='confirmed', delivery_mode='entrega')

    pendentes   = base.filter(Sale.dispatched_at == None).order_by(Sale.created_at.asc()).all()
    em_rota     = (base.filter(Sale.dispatched_at != None, Sale.delivered_at == None)
                       .order_by(Sale.dispatched_at.asc()).all())
    concluidas  = (Sale.query
                       .filter_by(tenant_id=tid(), delivery_mode='entrega')
                       .filter(Sale.delivered_at != None)
                       .order_by(Sale.delivered_at.desc()).limit(20).all())

    motoboys = Motoboy.query.filter_by(tenant_id=tid(), active=True).order_by(Motoboy.name).all()
    cfg = current_user.tenant.get_settings()

    # Mapa sale_id → pedido_online para exibir nome/endereço de pedidos do link
    todas_vendas = pendentes + em_rota + list(concluidas)
    sale_ids = [v.id for v in todas_vendas]
    pedidos_map = {}
    if sale_ids:
        for po in PedidoOnline.query.filter(PedidoOnline.sale_id.in_(sale_ids)).all():
            pedidos_map[po.sale_id] = po

    return render_template('despacho/index.html',
        pendentes=pendentes, em_rota=em_rota, concluidas=concluidas,
        motoboys=motoboys, cfg=cfg, pedidos_map=pedidos_map)

@despacho_bp.route('/<int:sale_id>/despachar', methods=['POST'])
@login_required
def despachar(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    motoboy_id = request.form.get('motoboy_id', type=int)

    motoboy = Motoboy.query.filter_by(id=motoboy_id, tenant_id=tid()).first() if motoboy_id else None
    sale.dispatched_at = datetime.now()
    sale.motoboy_id    = motoboy.id   if motoboy else None
    sale.motoboy_name  = motoboy.name if motoboy else None
    db.session.commit()

    cfg = current_user.tenant.get_settings()
    wa_url = None
    if cfg.get('whatsapp_notify') and sale.customer and sale.customer.phone:
        phone = ''.join(filter(str.isdigit, sale.customer.phone))
        if not phone.startswith('55'):
            phone = '55' + phone
        itens = ', '.join(f'{int(i.quantity)}x {i.product_name}' for i in sale.items)
        pgto_map = {
            'dinheiro': 'Dinheiro', 'cartao': 'Cartão', 'pix': 'Pix',
            'conta': 'Conta', 'pelo_app': 'Pelo app',
            'entrega_dinheiro': 'Dinheiro na entrega',
            'entrega_cartao': 'Cartão na entrega',
            'entrega_pix': 'Pix na entrega',
        }
        pagamento = pgto_map.get(sale.payment_method, sale.payment_method)
        total = f'R$ {sale.total:.2f}'.replace('.', ',')
        msg_tpl = cfg.get('whatsapp_msg') or 'Olá {cliente}! Seu pedido saiu para entrega com o motoboy {motoboy}. Em breve chegará até você!'
        msg = (msg_tpl
               .replace('{cliente}', sale.customer.name)
               .replace('{motoboy}', motoboy.name if motoboy else 'nosso entregador')
               .replace('{itens}', itens)
               .replace('{pagamento}', pagamento)
               .replace('{total}', total))
        import urllib.parse
        wa_url = f'whatsapp://send?phone={phone}&text={urllib.parse.quote(msg)}'

    return jsonify({'ok': True, 'wa_url': wa_url, 'sale_id': sale.id})

@despacho_bp.route('/<int:sale_id>/concluir', methods=['POST'])
@login_required
def concluir(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    sale.delivered_at = datetime.now()
    db.session.commit()
    return jsonify({'ok': True, 'sale_id': sale.id})

@despacho_bp.route('/<int:sale_id>/cancelar', methods=['POST'])
@login_required
def cancelar(sale_id):
    sale = Sale.query.filter_by(id=sale_id, tenant_id=tid()).first_or_404()
    motivo      = request.form.get('cancel_reason', '').strip()
    op_username = request.form.get('op_username', '').strip()
    op_password = request.form.get('op_password', '').strip()

    if not motivo:
        flash('Informe o motivo do cancelamento.', 'danger')
        return redirect(url_for('entregas.index'))

    from app.models.user import User
    from app.models.vale import Employee
    from werkzeug.security import check_password_hash
    autenticado = False
    nome_op = op_username
    u = User.query.filter_by(username=op_username, tenant_id=tid()).first()
    if u and u.check_password(op_password):
        autenticado = True
        nome_op = u.display_name or u.username
    if not autenticado:
        emp = Employee.query.filter_by(username=op_username, tenant_id=tid()).first()
        if emp and emp.password_hash and check_password_hash(emp.password_hash, op_password):
            autenticado = True
            nome_op = emp.name

    if not autenticado:
        flash('Usuário ou senha incorretos.', 'danger')
        return redirect(url_for('entregas.index'))

    sale.status            = 'cancelled'
    sale.cancelled_at      = datetime.now()
    sale.cancelled_by_id   = current_user.id
    sale.cancelled_by_name = nome_op
    sale.cancel_reason     = motivo
    db.session.commit()
    flash('Entrega cancelada.', 'warning')
    return redirect(url_for('entregas.index'))

@despacho_bp.route('/relatorio-motoboys')
@login_required
def relatorio_motoboys():
    hoje = date.today()
    de_str  = request.args.get('de',  hoje.isoformat())
    ate_str = request.args.get('ate', hoje.isoformat())
    motoboy_filtro = request.args.get('motoboy_id', '', type=str)

    try:
        de_dt  = datetime.combine(date.fromisoformat(de_str),  datetime.min.time())
        ate_dt = datetime.combine(date.fromisoformat(ate_str), datetime.max.time())
    except ValueError:
        de_dt  = datetime.combine(hoje, datetime.min.time())
        ate_dt = datetime.combine(hoje, datetime.max.time())

    # Base: todas as entregas com motoboy no período (sem filtro de motoboy ainda)
    base_periodo = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.motoboy_id.isnot(None),
        Sale.dispatched_at >= de_dt,
        Sale.dispatched_at <= ate_dt,
    )

    # Dropdown: somente motoboys que tiveram entregas NESTE período
    # (assim quem foi desligado aparece nos meses que trabalhou e some depois)
    motoboys = []
    _vistos = set()
    for v in base_periodo.order_by(Sale.dispatched_at.asc()).all():
        if v.motoboy_id not in _vistos:
            _vistos.add(v.motoboy_id)
            motoboys.append({'id': v.motoboy_id, 'name': v.motoboy_name or 'Motoboy'})
    motoboys.sort(key=lambda m: m['name'])

    # Aplica filtro de motoboy específico ao resultado
    query = base_periodo
    if motoboy_filtro:
        query = query.filter(Sale.motoboy_id == int(motoboy_filtro))

    vendas = query.order_by(Sale.dispatched_at.asc()).all()

    # agrupa por motoboy
    grupos = defaultdict(lambda: {'nome': '', 'entregas': [], 'total_frete': 0.0})
    for v in vendas:
        g = grupos[v.motoboy_id]
        g['nome'] = v.motoboy_name or 'Motoboy'
        g['entregas'].append(v)
        g['total_frete'] += (v.delivery_fee or 0)

    resumo = sorted(grupos.items(), key=lambda x: x[1]['nome'])

    return render_template('despacho/relatorio_motoboys.html',
        resumo=resumo,
        motoboys=motoboys,
        de_str=de_str,
        ate_str=ate_str,
        motoboy_filtro=motoboy_filtro,
        total_entregas=len(vendas),
    )
