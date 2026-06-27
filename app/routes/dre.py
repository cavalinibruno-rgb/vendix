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

    # Vendas confirmadas no período (ativas ou canceladas — todas que passaram pelo caixa)
    vendas = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status.in_(['confirmed', 'cancelled']),
        Sale.created_at >= inicio,
        Sale.created_at <= fim,
    ).all()

    confirmadas = [v for v in vendas if v.status == 'confirmed']
    canceladas  = [v for v in vendas if v.status == 'cancelled']

    receita_bruta      = sum(v.total for v in vendas)
    deducao_cancelados = sum(v.total for v in canceladas)
    base_imposto       = sum(v.total for v in confirmadas)

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
    if current_user.is_employee:
        from flask import abort
        abort(403)
    hoje = date.today()
    inicio_str = request.args.get('inicio', hoje.replace(day=1).strftime('%Y-%m-%d'))
    fim_str    = request.args.get('fim',    hoje.strftime('%Y-%m-%d'))
    ctx = _calcular_dre(inicio_str, fim_str)
    return render_template('dre/index.html', **ctx)

def _money(v):
    """Formata em padrão brasileiro: R$ 1.234,56"""
    return 'R$ ' + f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

def _br_date(s):
    return f'{s[8:10]}/{s[5:7]}/{s[0:4]}'

def _gerar_pdf_dre(ctx):
    from fpdf import FPDF

    regime_labels = {
        'mei': 'MEI', 'simples': 'Simples Nacional',
        'presumido': 'Lucro Presumido', 'real': 'Lucro Real',
    }
    store = ctx['store_name']
    gerado_em = datetime.now()

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=18)

    def _footer():
        pdf.set_y(-15)
        pdf.set_font('Helvetica', '', 7)
        pdf.set_text_color(150)
        pdf.cell(0, 5, f'{store} - Relatorio gerado pelo sistema Vendix', 0, 0, 'L')
        pdf.cell(0, 5, gerado_em.strftime('%d/%m/%Y %H:%M'), 0, 0, 'R')
    pdf.footer = _footer

    pdf.add_page()
    pdf.set_margins(16, 16, 16)
    W = pdf.w - 32  # largura útil ≈ 178mm

    # ── Cabeçalho ──
    pdf.set_text_color(26, 26, 46)
    pdf.set_font('Helvetica', 'B', 20)
    pdf.cell(0, 10, store, 0, 1, 'L')
    pdf.set_font('Helvetica', '', 11)
    pdf.set_text_color(90)
    pdf.cell(0, 6, 'Demonstracao do Resultado do Exercicio (DRE)', 0, 1, 'L')
    # Badge regime
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(26, 26, 46)
    pdf.set_text_color(201, 168, 76)
    label = regime_labels.get(ctx['regime'], '')
    pdf.cell(pdf.get_string_width(label) + 8, 6, label, 0, 1, 'C', True)
    # Linha dourada
    y = pdf.get_y() + 2
    pdf.set_draw_color(201, 168, 76)
    pdf.set_line_width(0.8)
    pdf.line(16, y, 16 + W, y)
    pdf.ln(6)

    # ── Período ──
    pdf.set_fill_color(245, 243, 236)
    pdf.set_draw_color(224, 216, 192)
    pdf.set_line_width(0.2)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(40)
    periodo = f"Periodo: {_br_date(ctx['inicio'])} a {_br_date(ctx['fim'])}"
    vendas_txt = f"{ctx['qtd_vendas']} vendas"
    pdf.cell(W * 0.6, 9, '  ' + periodo, 1, 0, 'L', True)
    pdf.cell(W * 0.4, 9, vendas_txt + '  ', 1, 1, 'R', True)
    pdf.ln(4)

    # ── Helpers de layout ──
    def secao(titulo):
        pdf.ln(3)
        yy = pdf.get_y()
        pdf.set_fill_color(201, 168, 76)
        pdf.rect(16, yy, 1.5, 6, 'F')
        pdf.set_xy(20, yy)
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_text_color(26, 26, 46)
        pdf.cell(0, 6, titulo, 0, 1)
        pdf.ln(1)

    def row(label, value, strong=False, sub=False, vcolor=(26, 26, 46)):
        fill = strong
        if strong:
            pdf.set_fill_color(245, 245, 248)
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_text_color(26, 26, 46)
        else:
            pdf.set_font('Helvetica', '', 9 if sub else 10)
            pdf.set_text_color(115, 115, 115) if sub else pdf.set_text_color(40, 40, 40)
        lw = W - 45
        label_txt = ('     ' + label) if sub else label
        pdf.cell(lw, 7, label_txt, 0, 0, 'L', fill)
        pdf.set_text_color(*vcolor)
        pdf.cell(45, 7, value, 0, 1, 'R', fill)

    RED = (192, 57, 43)
    GREEN = (30, 122, 68)

    # ── DEMONSTRATIVO ──
    secao('Resultado do Periodo')
    row('Receita Bruta de Vendas', _money(ctx['receita_bruta']), strong=True, vcolor=GREEN)
    if ctx['deducao_cancelados'] > 0:
        row('(-) Cancelamentos / Devolucoes', '- ' + _money(ctx['deducao_cancelados']), sub=True, vcolor=RED)
    if ctx['reduz_receita'] and ctx['total_impostos'] > 0:
        for lab, val in ctx['impostos_detalhado'].items():
            row('(-) ' + lab, '- ' + _money(val), sub=True, vcolor=RED)
    row('Receita Liquida', _money(ctx['receita_liquida']), strong=True)
    row('(-) CMV - Custo das Mercadorias Vendidas', '- ' + _money(ctx['cmv']), sub=True, vcolor=RED)
    lb_color = GREEN if ctx['lucro_bruto'] >= 0 else RED
    row('Lucro Bruto', _money(ctx['lucro_bruto']), strong=True, vcolor=lb_color)
    row('(-) Despesas Operacionais', '- ' + _money(ctx['total_despesas']), sub=True, vcolor=RED)
    if ctx['regime'] == 'mei' and ctx['das_mei'] > 0:
        row('(-) DAS MEI (fixo mensal)', '- ' + _money(ctx['das_mei']), sub=True, vcolor=RED)

    # ── RESULTADO ──
    pdf.ln(2)
    rl = ctx['resultado_liquido']
    if rl >= 0:
        pdf.set_fill_color(230, 244, 234); tc = GREEN; titulo = 'LUCRO LIQUIDO'
    else:
        pdf.set_fill_color(251, 233, 231); tc = RED; titulo = 'PREJUIZO'
    pdf.set_text_color(*tc)
    pdf.set_font('Helvetica', 'B', 13)
    pdf.cell(W - 55, 12, '  ' + titulo, 0, 0, 'L', True)
    pdf.cell(55, 12, _money(abs(rl)) + '  ', 0, 1, 'R', True)

    # ── DESPESAS POR CATEGORIA ──
    secao('Despesas por Categoria')
    if ctx['por_categoria']:
        td = ctx['total_despesas']
        for cat, val in sorted(ctx['por_categoria'].items(), key=lambda x: x[1], reverse=True):
            pdf.set_font('Helvetica', '', 10)
            pdf.set_text_color(40)
            pct = f"{(val / td * 100):.0f}%" if td else '0%'
            pdf.cell(W - 75, 7, cat, 0, 0, 'L')
            pdf.set_text_color(*RED)
            pdf.cell(45, 7, _money(val), 0, 0, 'R')
            pdf.set_text_color(150)
            pdf.cell(30, 7, pct, 0, 1, 'R')
        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_fill_color(245, 245, 248)
        pdf.set_text_color(26, 26, 46)
        pdf.cell(W - 75, 7, 'Total', 0, 0, 'L', True)
        pdf.set_text_color(*RED)
        pdf.cell(45, 7, _money(td), 0, 0, 'R', True)
        pdf.set_text_color(150)
        pdf.cell(30, 7, '100%', 0, 1, 'R', True)
    else:
        pdf.set_font('Helvetica', 'I', 10)
        pdf.set_text_color(150)
        pdf.cell(0, 7, 'Nenhuma despesa no periodo.', 0, 1)

    # ── INDICADORES ──
    secao('Indicadores')
    rliq = ctx['receita_liquida']
    rbru = ctx['receita_bruta']
    qv = ctx['qtd_vendas']
    indicadores = [
        ('Margem Bruta',        f"{(ctx['lucro_bruto'] / rliq * 100):.1f}%" if rliq else '0.0%'),
        ('Margem Liquida',      f"{(rl / rbru * 100):.1f}%" if rbru else '0.0%'),
        ('Ticket Medio',        _money(rbru / qv) if qv else _money(0)),
        ('CMV sobre Receita',   f"{(ctx['cmv'] / rliq * 100):.1f}%" if rliq else '0.0%'),
    ]
    for lab, val in indicadores:
        pdf.set_font('Helvetica', '', 10)
        pdf.set_text_color(40)
        pdf.cell(W - 45, 7, lab, 0, 0, 'L')
        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_text_color(26, 26, 46)
        pdf.cell(45, 7, val, 0, 1, 'R')

    # ── LISTA DE DESPESAS ──
    if ctx['despesas']:
        secao('Despesas do Periodo')
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_text_color(130)
        pdf.set_draw_color(220)
        pdf.cell(28, 6, 'DATA', 'B', 0, 'L')
        pdf.cell(45, 6, 'CATEGORIA', 'B', 0, 'L')
        pdf.cell(W - 28 - 45 - 35, 6, 'DESCRICAO', 'B', 0, 'L')
        pdf.cell(35, 6, 'VALOR', 'B', 1, 'R')
        for d in ctx['despesas']:
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(50)
            desc = (d.description or '-')[:48]
            pdf.cell(28, 6, d.date.strftime('%d/%m/%Y'), 0, 0, 'L')
            pdf.cell(45, 6, d.category[:24], 0, 0, 'L')
            pdf.cell(W - 28 - 45 - 35, 6, desc, 0, 0, 'L')
            pdf.set_text_color(*RED)
            pdf.cell(35, 6, _money(d.amount), 0, 1, 'R')

    return bytes(pdf.output())

@dre_bp.route('/pdf')
@login_required
def pdf():
    from flask import make_response
    hoje = date.today()
    inicio_str = request.args.get('inicio', hoje.replace(day=1).strftime('%Y-%m-%d'))
    fim_str    = request.args.get('fim',    hoje.strftime('%Y-%m-%d'))
    ctx = _calcular_dre(inicio_str, fim_str)
    pdf_bytes = _gerar_pdf_dre(ctx)
    resp = make_response(pdf_bytes)
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = f'attachment; filename=DRE_{inicio_str}_a_{fim_str}.pdf'
    return resp

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
