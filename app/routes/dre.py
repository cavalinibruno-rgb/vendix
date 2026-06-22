from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.sale import Sale, SaleItem
from app.models.product import Product
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

def _calcular_impostos(regime, cfg, base):
    """Retorna (dict_detalhado, total, reduz_receita).
    reduz_receita=False para MEI (DAS vai para despesas, não deduz receita).
    """
    if regime == 'mei':
        das = cfg.get('das_mei', 0)
        return {'DAS MEI (fixo mensal)': das}, das, False

    if regime == 'simples':
        aliq = cfg.get('aliquota_simples', 0)
        valor = base * (aliq / 100)
        return {f'Simples Nacional ({aliq:.2f}%)': valor}, valor, True

    # presumido ou real
    campos = [
        ('aliq_pis',   'PIS'),
        ('aliq_cofins','COFINS'),
        ('aliq_iss',   'ISS'),
        ('aliq_icms',  'ICMS'),
        ('aliq_irpj',  'IRPJ'),
        ('aliq_csll',  'CSLL'),
    ]
    detalhado = {}
    for key, label in campos:
        aliq = cfg.get(key, 0)
        if aliq:
            detalhado[f'{label} ({aliq:.2f}%)'] = base * (aliq / 100)
    total = sum(detalhado.values())
    return detalhado, total, True

def _calcular_dre(inicio_str, fim_str):
    """Calcula todos os números da DRE para o período. Retorna dict de contexto."""
    tenant = Tenant.query.get(tid())
    cfg    = tenant.get_settings()
    regime = cfg.get('regime_tributario', 'simples')

    inicio = datetime.strptime(inicio_str, '%Y-%m-%d')
    fim    = datetime.strptime(fim_str,    '%Y-%m-%d').replace(hour=23, minute=59, second=59)

    # Vendas confirmadas no período
    vendas = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.created_at >= inicio,
        Sale.created_at <= fim,
    ).all()

    # Vendas canceladas no período
    canceladas = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'cancelled',
        Sale.cancelled_at >= inicio,
        Sale.cancelled_at <= fim,
    ).all()

    receita_bruta      = sum(v.total for v in vendas)
    deducao_cancelados = sum(v.total for v in canceladas)
    base_imposto       = receita_bruta - deducao_cancelados

    impostos_detalhado, total_impostos, reduz_receita = _calcular_impostos(regime, cfg, base_imposto)

    deducao_impostos = total_impostos if reduz_receita else 0
    total_deducoes   = deducao_cancelados + deducao_impostos
    receita_liquida  = receita_bruta - total_deducoes

    # Para MEI o DAS entra como despesa extra, não reduz receita
    das_mei = total_impostos if regime == 'mei' else 0

    # CMV — usa custo gravado no item; fallback para custo atual do produto em vendas antigas
    _produto_cache = {}
    def _custo_item(item):
        if item.cost_price:
            return item.cost_price
        if item.product_id:
            if item.product_id not in _produto_cache:
                _produto_cache[item.product_id] = Product.query.get(item.product_id)
            p = _produto_cache[item.product_id]
            return (p.cost_price or 0) if p else 0
        return 0

    cmv = sum(_custo_item(item) * item.quantity for v in vendas for item in v.items)

    lucro_bruto = receita_liquida - cmv

    # Despesas operacionais
    despesas = Expense.query.filter(
        Expense.tenant_id == tid(),
        Expense.date >= inicio.date(),
        Expense.date <= fim.date(),
    ).order_by(Expense.date.desc()).all()

    total_despesas    = sum(d.amount for d in despesas)
    resultado_liquido = lucro_bruto - total_despesas - das_mei

    # Agrupamento por categoria
    por_categoria = {}
    for d in despesas:
        por_categoria[d.category] = por_categoria.get(d.category, 0) + d.amount

    return dict(
        inicio=inicio_str, fim=fim_str,
        regime=regime, cfg=cfg,
        store_name=tenant.store_name,
        impostos_detalhado=impostos_detalhado,
        total_impostos=total_impostos,
        reduz_receita=reduz_receita,
        das_mei=das_mei,
        receita_bruta=receita_bruta,
        deducao_cancelados=deducao_cancelados,
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

@dre_bp.route('/')
@login_required
def index():
    hoje = date.today()
    inicio_str = request.args.get('inicio', hoje.replace(day=1).strftime('%Y-%m-%d'))
    fim_str    = request.args.get('fim',    hoje.strftime('%Y-%m-%d'))
    ctx = _calcular_dre(inicio_str, fim_str)
    return render_template('dre/index.html', **ctx)

@dre_bp.route('/pdf')
@login_required
def pdf():
    hoje = date.today()
    inicio_str = request.args.get('inicio', hoje.replace(day=1).strftime('%Y-%m-%d'))
    fim_str    = request.args.get('fim',    hoje.strftime('%Y-%m-%d'))
    ctx = _calcular_dre(inicio_str, fim_str)
    ctx['gerado_em'] = datetime.now()
    return render_template('dre/relatorio_pdf.html', **ctx)

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
