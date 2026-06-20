from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.sale import Sale, SaleItem
from app.models.expense import Expense, CATEGORIAS
from app.models.tenant import Tenant
from datetime import date, datetime

dre_bp = Blueprint('dre', __name__, url_prefix='/dre')

def tid():
    return current_user.tenant_id

def fval(name, default='0'):
    v = request.form.get(name, default).replace(',', '.').strip() or default
    try:
        return float(v)
    except ValueError:
        return 0.0

@dre_bp.route('/')
@login_required
def index():
    # Período — padrão: mês atual
    hoje = date.today()
    inicio_str = request.args.get('inicio', hoje.replace(day=1).strftime('%Y-%m-%d'))
    fim_str    = request.args.get('fim',    hoje.strftime('%Y-%m-%d'))
    inicio = datetime.strptime(inicio_str, '%Y-%m-%d')
    fim    = datetime.strptime(fim_str,    '%Y-%m-%d').replace(hour=23, minute=59, second=59)

    aliquota = float(request.args.get('aliquota', '0') or '0')

    # Vendas confirmadas no período
    vendas = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.created_at >= inicio,
        Sale.created_at <= fim,
    ).all()

    # Vendas canceladas no período (deduções)
    canceladas = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'cancelled',
        Sale.cancelled_at >= inicio,
        Sale.cancelled_at <= fim,
    ).all()

    receita_bruta      = sum(v.total for v in vendas)
    deducao_cancelados = sum(v.total for v in canceladas)
    base_imposto       = receita_bruta - deducao_cancelados
    deducao_impostos   = base_imposto * (aliquota / 100)
    total_deducoes     = deducao_cancelados + deducao_impostos
    receita_liquida    = receita_bruta - total_deducoes

    # CMV — usa custo gravado no momento da venda (histórico fiel)
    cmv = sum(
        (item.cost_price or 0) * item.quantity
        for v in vendas
        for item in v.items
    )

    lucro_bruto = receita_liquida - cmv

    # Despesas operacionais
    despesas = Expense.query.filter(
        Expense.tenant_id == tid(),
        Expense.date >= inicio.date(),
        Expense.date <= fim.date(),
    ).order_by(Expense.date.desc()).all()

    total_despesas  = sum(d.amount for d in despesas)
    resultado_liquido = lucro_bruto - total_despesas

    # Agrupamento por categoria
    por_categoria = {}
    for d in despesas:
        por_categoria[d.category] = por_categoria.get(d.category, 0) + d.amount

    return render_template('dre/index.html',
        inicio=inicio_str, fim=fim_str, aliquota=aliquota,
        receita_bruta=receita_bruta,
        deducao_cancelados=deducao_cancelados,
        deducao_impostos=deducao_impostos,
        total_deducoes=total_deducoes,
        receita_liquida=receita_liquida,
        cmv=cmv,
        lucro_bruto=lucro_bruto,
        despesas=despesas,
        total_despesas=total_despesas,
        por_categoria=por_categoria,
        resultado_liquido=resultado_liquido,
        categorias=CATEGORIAS,
        qtd_vendas=len(vendas),
    )

@dre_bp.route('/despesa/nova', methods=['POST'])
@login_required
def despesa_nova():
    date_str  = request.form.get('date', date.today().strftime('%Y-%m-%d'))
    category  = request.form.get('category', '').strip()
    descricao = request.form.get('description', '').strip()
    valor     = fval('amount')

    if not category or valor <= 0:
        flash('Preencha categoria e valor.', 'danger')
        return redirect(url_for('dre.index'))

    d = Expense(
        tenant_id   = tid(),
        date        = datetime.strptime(date_str, '%Y-%m-%d').date(),
        category    = category,
        description = descricao or None,
        amount      = valor,
    )
    db.session.add(d)
    db.session.commit()
    flash('Despesa registrada.', 'success')
    return redirect(request.referrer or url_for('dre.index'))

@dre_bp.route('/despesa/<int:eid>/excluir', methods=['POST'])
@login_required
def despesa_excluir(eid):
    d = Expense.query.filter_by(id=eid, tenant_id=tid()).first_or_404()
    db.session.delete(d)
    db.session.commit()
    flash('Despesa removida.', 'success')
    return redirect(request.referrer or url_for('dre.index'))
