from flask import Blueprint, render_template, redirect, url_for, request, flash
import json
from flask_login import login_required, current_user
from app import db
from app.models.cash import CashRegister
from app.models.cash_withdrawal import CashWithdrawal
from app.models.expense import Expense, CATEGORIAS
from app.models.sale import Sale
from app.models.vale import Employee
from app.auth_utils import autenticar_operador
from datetime import datetime
from sqlalchemy import func

cash_bp = Blueprint('cash', __name__, url_prefix='/caixa')

def _user_id():
    # Funcionários (EmployeeLoginProxy, id "e_<n>") não estão na tabela users;
    # colunas FK->users recebem None. A autoria fica nos campos *_name.
    uid = current_user.id
    if isinstance(uid, str) and uid.startswith('e_'):
        return None
    return uid


def tid():
    return current_user.tenant_id

def caixa_aberto():
    return CashRegister.query.filter_by(tenant_id=tid(), status='open').first()

def _entra_no_caixa(venda):
    """Entregas só entram no caixa quando concluídas (motoboy voltou). Retiradas entram imediatamente."""
    if venda.delivery_mode == 'entrega':
        return venda.delivered_at is not None
    # retirada: loja entra sempre; app só se pago na entrega
    if venda.source == 'loja' or venda.source is None:
        return True
    return venda.payment_method in ('entrega_dinheiro', 'entrega_cartao', 'entrega_pix')

@cash_bp.route('/')
@login_required
def index():
    caixa = caixa_aberto()
    historico = CashRegister.query.filter_by(tenant_id=tid(), status='closed')\
                                  .order_by(CashRegister.closed_at.desc()).limit(30).all()
    retiradas = []
    total_retiradas = 0.0
    despesas = []
    total_despesas = 0.0
    if caixa:
        retiradas = CashWithdrawal.query.filter_by(tenant_id=tid(), cash_register_id=caixa.id).all()
        total_retiradas = sum(r.amount for r in retiradas)
        despesas = Expense.query.filter_by(tenant_id=tid(), cash_register_id=caixa.id).order_by(Expense.created_at).all()
        total_despesas = sum(d.amount for d in despesas)
    return render_template('cash/index.html', caixa=caixa, historico=historico,
                           retiradas=retiradas, total_retiradas=total_retiradas,
                           despesas=despesas, total_despesas=total_despesas,
                           categorias=CATEGORIAS)

@cash_bp.route('/abrir', methods=['POST'])
@login_required
def abrir():
    if caixa_aberto():
        flash('Já existe um caixa aberto.', 'warning')
        return redirect(url_for('cash.index'))

    modo  = request.form.get('modo', 'lojista')
    valor = float((request.form.get('opening_amount', '0') or '0').replace(',', '.'))

    username = request.form.get('op_username', '').strip()
    senha    = request.form.get('op_password', '').strip()
    nome, ok = autenticar_operador(tid(), username, senha)
    if not ok:
        flash('Usuário ou senha incorretos.', 'danger')
        return redirect(url_for('cash.index'))

    if modo == 'funcionario':
        emp = Employee.query.filter_by(tenant_id=tid(), username=username, role='caixa').first()
        operator_employee_id = emp.id if emp else None
    else:
        operator_employee_id = None

    operator_name = nome

    caixa = CashRegister(
        tenant_id            = tid(),
        opened_by            = _user_id(),
        opening_amount       = valor,
        operator_employee_id = operator_employee_id,
        operator_name        = operator_name,
        status               = 'open',
    )
    db.session.add(caixa)
    db.session.commit()
    flash(f'Caixa aberto por {operator_name}. Troco inicial: R$ {valor:.2f}', 'success')
    return redirect(url_for('cash.index'))

@cash_bp.route('/retirada', methods=['POST'])
@login_required
def retirada():
    caixa = caixa_aberto()
    if not caixa:
        flash('Nenhum caixa aberto.', 'warning')
        return redirect(url_for('cash.index'))

    def fval(name):
        v = request.form.get(name, '0').replace(',', '.').strip() or '0'
        try: return float(v)
        except ValueError: return 0.0

    valor       = fval('amount')
    motivo      = request.form.get('motivo', '').strip()
    op_username = request.form.get('op_username', '').strip()
    op_password = request.form.get('op_password', '').strip()

    if valor <= 0:
        flash('Informe um valor válido.', 'danger')
        return redirect(url_for('cash.index'))
    if not motivo:
        flash('Informe o motivo da retirada.', 'danger')
        return redirect(url_for('cash.index'))

    nome_resp, ok = autenticar_operador(tid(), op_username, op_password)
    if not ok:
        flash('Usuário ou senha incorretos.', 'danger')
        return redirect(url_for('cash.index'))

    w = CashWithdrawal(
        tenant_id        = tid(),
        cash_register_id = caixa.id,
        amount           = valor,
        motivo           = motivo,
        operator_name    = nome_resp,
    )
    db.session.add(w)
    db.session.commit()
    flash(f'Retirada de R$ {valor:.2f} registrada por {nome_resp}.', 'success')
    return redirect(url_for('cash.index'))

@cash_bp.route('/despesa', methods=['POST'])
@login_required
def despesa():
    from datetime import date
    caixa = caixa_aberto()
    if not caixa:
        flash('Nenhum caixa aberto.', 'warning')
        return redirect(url_for('cash.index'))

    def fval(name):
        v = request.form.get(name, '0').replace(',', '.').strip() or '0'
        try: return float(v)
        except ValueError: return 0.0

    valor          = fval('amount')
    categoria      = request.form.get('categoria', '').strip()
    descricao      = request.form.get('descricao', '').strip()
    pagamento      = request.form.get('payment_method', 'dinheiro')
    op_username    = request.form.get('op_username', '').strip()
    op_password    = request.form.get('op_password', '').strip()

    if valor <= 0:
        flash('Informe um valor válido.', 'danger')
        return redirect(url_for('cash.index'))
    if not categoria:
        flash('Selecione uma categoria.', 'danger')
        return redirect(url_for('cash.index'))

    nome_resp, ok = autenticar_operador(tid(), op_username, op_password)
    if not ok:
        flash('Usuário ou senha incorretos.', 'danger')
        return redirect(url_for('cash.index'))

    db.session.add(Expense(
        tenant_id        = tid(),
        cash_register_id = caixa.id,
        date             = date.today(),
        category         = categoria,
        description      = descricao or None,
        amount           = valor,
        payment_method   = pagamento,
        operator_name    = nome_resp,
    ))
    db.session.commit()
    flash(f'Despesa de R$ {valor:.2f} registrada por {nome_resp}.', 'success')
    return redirect(url_for('cash.index'))

@cash_bp.route('/<int:caixa_id>/fechar', methods=['GET', 'POST'])
@login_required
def fechar(caixa_id):
    caixa = CashRegister.query.filter_by(id=caixa_id, tenant_id=tid(), status='open').first_or_404()

    # Vendas do período — loja + app com pagamento na entrega (entram no caixa físico)
    todas_vendas = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.created_at >= caixa.opened_at,
    ).all()

    vendas = [v for v in todas_vendas if _entra_no_caixa(v)]

    total_dinheiro    = sum(v.total for v in vendas if v.payment_method in ('dinheiro', 'entrega_dinheiro'))
    total_credito     = sum(v.total for v in vendas if v.payment_method in ('cartao_credito', 'entrega_cartao_credito', 'cartao', 'entrega_cartao'))
    total_debito      = sum(v.total for v in vendas if v.payment_method in ('cartao_debito', 'entrega_cartao_debito'))
    total_cartao      = total_credito + total_debito
    total_pix         = sum(v.total for v in vendas if v.payment_method in ('pix', 'entrega_pix'))
    total_conta       = sum(v.total for v in vendas if v.payment_method == 'conta')
    total_funcionario = sum(v.total for v in vendas if v.payment_method == 'funcionario')
    total_geral       = sum(v.total for v in vendas)
    retiradas         = CashWithdrawal.query.filter_by(tenant_id=tid(), cash_register_id=caixa.id).all()
    total_retiradas   = sum(r.amount for r in retiradas)
    despesas          = Expense.query.filter_by(tenant_id=tid(), cash_register_id=caixa.id).all()
    despesas_dinheiro = sum(d.amount for d in despesas if d.payment_method == 'dinheiro')
    # Esperado na gaveta = abertura + vendas dinheiro - retiradas - despesas em dinheiro
    esperado_caixa    = caixa.opening_amount + total_dinheiro - total_retiradas - despesas_dinheiro

    # Bloqueia fechamento se há entregas em rota (despachadas mas não concluídas)
    em_rota = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.delivery_mode == 'entrega',
        Sale.dispatched_at != None,
        Sale.delivered_at == None,
    ).count()

    if request.method == 'POST':
        if em_rota > 0:
            flash(f'Há {em_rota} entrega(s) ainda em rota. Conclua todas antes de fechar o caixa.', 'danger')
            return redirect(url_for('cash.fechar', caixa_id=caixa_id))
        def fval(name):
            v = request.form.get(name, '0').replace(',', '.').strip() or '0'
            try: return float(v)
            except ValueError: return 0.0
        op = {
            'dinheiro':    fval('dinheiro'),
            'credito':     fval('credito'),
            'debito':      fval('debito'),
            'pix':         fval('pix'),
            'conta':       fval('conta'),
            'funcionario': fval('funcionario'),
        }
        total_operador = sum(op.values())
        caixa.closing_amount = total_operador
        caixa.closing_data   = json.dumps(op)
        caixa.closed_by      = _user_id()
        caixa.closed_at      = datetime.now()
        caixa.status         = 'closed'
        caixa.notes          = request.form.get('notes', '')
        db.session.commit()
        flash('Caixa fechado com sucesso!', 'success')
        return redirect(url_for('cash.resumo', caixa_id=caixa.id))

    return render_template('cash/fechar.html',
        caixa=caixa, vendas=vendas,
        total_dinheiro=total_dinheiro,
        total_credito=total_credito, total_debito=total_debito,
        total_cartao=total_cartao,
        total_pix=total_pix, total_conta=total_conta,
        total_funcionario=total_funcionario,
        total_geral=total_geral, esperado_caixa=esperado_caixa,
        retiradas=retiradas, total_retiradas=total_retiradas,
        despesas=despesas, despesas_dinheiro=despesas_dinheiro,
        em_rota=em_rota,
    )

def _calcular_resumo(caixa):
    """Calcula conferência (sistema vs operador), retiradas e vendas do caixa.
    Reaproveitado pela tela de resumo e pela impressão ESC/POS."""
    todas_vendas = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.created_at >= caixa.opened_at,
        Sale.created_at <= (caixa.closed_at or datetime.now()),
    ).all()

    vendas_loja = [v for v in todas_vendas if v.source != 'app' and v.status == 'confirmed']
    vendas_app  = [v for v in todas_vendas if v.source == 'app'  and v.status == 'confirmed']

    def tot(lst, methods): return sum(v.total for v in lst if v.payment_method in methods)

    todas = vendas_loja + vendas_app
    desp  = Expense.query.filter_by(cash_register_id=caixa.id).all()
    desp_din = sum(d.amount for d in desp if d.payment_method == 'dinheiro')
    desp_pix = sum(d.amount for d in desp if d.payment_method == 'pix')
    retiradas       = CashWithdrawal.query.filter_by(cash_register_id=caixa.id).all()
    total_retiradas = sum(r.amount for r in retiradas)
    sis = {
        'dinheiro':    caixa.opening_amount + tot(todas, ('dinheiro', 'entrega_dinheiro')) - total_retiradas - desp_din,
        'credito':     tot(todas, ('cartao_credito', 'entrega_cartao_credito', 'cartao', 'entrega_cartao')),
        'debito':      tot(todas, ('cartao_debito', 'entrega_cartao_debito')),
        'pix':         tot(todas, ('pix', 'entrega_pix')) - desp_pix,
        'conta':       tot(todas, ('conta',)),
        'funcionario': tot(todas, ('funcionario',)),
    }

    op = json.loads(caixa.closing_data) if caixa.closing_data else {k: 0 for k in sis}

    conferencia = []
    for key, label, icon, color in [
        ('dinheiro',    'Dinheiro (gaveta)',  'bi-cash',              'text-success'),
        ('credito',     'Cartão Crédito',    'bi-credit-card',       'text-primary'),
        ('debito',      'Cartão Débito',     'bi-credit-card-2-back','text-primary'),
        ('pix',         'Pix',               'bi-qr-code',           'text-info'),
        ('conta',       'Conta (fiado)',      'bi-person-lines-fill', 'text-warning'),
        ('funcionario', 'Funcionário (vale)', 'bi-person-badge',      'text-secondary'),
    ]:
        s = sis.get(key, 0)
        o = op.get(key, 0)
        conferencia.append({'label': label, 'icon': icon, 'color': color,
                            'sistema': s, 'operador': o, 'diff': o - s})

    total_sistema  = sum(sis.values())
    total_operador = sum(op.values())

    return dict(
        vendas=vendas_loja + vendas_app,
        conferencia=conferencia,
        total_sistema=total_sistema,
        total_operador=total_operador,
        diff_total=total_operador - total_sistema,
        retiradas=retiradas,
        total_retiradas=total_retiradas,
    )


@cash_bp.route('/<int:caixa_id>/resumo')
@login_required
def resumo(caixa_id):
    caixa = CashRegister.query.filter_by(id=caixa_id, tenant_id=tid()).first_or_404()
    ctx = _calcular_resumo(caixa)
    return render_template('cash/resumo.html', caixa=caixa, **ctx)


@cash_bp.route('/<int:caixa_id>/escpos')
@login_required
def escpos(caixa_id):
    from flask import Response
    caixa = CashRegister.query.filter_by(id=caixa_id, tenant_id=tid()).first_or_404()
    ctx = _calcular_resumo(caixa)
    store_name = current_user.tenant.store_name or 'Vendix'

    W = 42
    INIT   = b'\x1b@'
    CP850  = b'\x1bt\x02'
    CENTER = b'\x1ba\x01'
    LEFT   = b'\x1ba\x00'
    BON    = b'\x1bE\x01'
    BOFF   = b'\x1bE\x00'
    CUT    = b'\x1dV\x01'
    NL     = b'\n'

    def enc(s):  return s.encode('cp850', errors='replace')
    def ctr(s):  return CENTER + enc(s[:W].center(W)) + NL
    def lft(s):  return LEFT + enc(s[:W]) + NL
    def cols(l, r):
        r = str(r); l = str(l)[:W - len(r) - 1]
        return LEFT + enc(l.ljust(W - len(r)) + r) + NL
    def sep(c='-'): return LEFT + enc(c * W) + NL
    def brl(v): return f'R${v:.2f}'

    d  = INIT + CP850
    d += CENTER + BON + enc(store_name.upper()[:W].center(W)) + BOFF + NL
    d += sep('=')
    d += ctr(f'FECHAMENTO DE CAIXA #{caixa.id}')
    if caixa.operator_name:
        d += ctr(f'Operador: {caixa.operator_name}')
    d += sep('=')
    d += lft(f'Aberto:  {caixa.opened_at.strftime("%d/%m/%Y %H:%M")}')
    if caixa.closed_at:
        d += lft(f'Fechado: {caixa.closed_at.strftime("%d/%m/%Y %H:%M")}')
    d += cols('Troco inicial', brl(caixa.opening_amount))
    d += sep()

    # Conferência: Sistema vs Operador
    d += lft('CONFERENCIA (sistema x operador)')
    d += sep()
    for c in ctx['conferencia']:
        d += lft(c['label'])
        d += cols('  Sistema', brl(c['sistema']))
        d += cols('  Operador', brl(c['operador']))
        sinal = '+' if c['diff'] > 0 else ''
        d += cols('  Diferenca', f'{sinal}{brl(c["diff"])}')
        d += sep('.')
    d += sep('=')
    d += cols('TOTAL SISTEMA', brl(ctx['total_sistema']))
    d += cols('TOTAL OPERADOR', brl(ctx['total_operador']))
    dt = ctx['diff_total']
    if dt == 0:
        d += BON + ctr('*** VALORES CONFEREM ***') + BOFF
    elif dt > 0:
        d += BON + cols('SOBRA', f'+{brl(dt)}') + BOFF
    else:
        d += BON + cols('FALTA', brl(dt)) + BOFF
    d += sep('=')

    if ctx['retiradas']:
        d += lft('RETIRADAS')
        for r in ctx['retiradas']:
            d += cols(f'{r.created_at.strftime("%H:%M")} {r.motivo}'[:W-12], f'-{brl(r.amount)}')
        d += cols('Total retiradas', f'-{brl(ctx["total_retiradas"])}')
        d += sep()

    d += cols('Qtd. vendas', str(len(ctx['vendas'])))
    d += NL
    d += ctr(datetime.now().strftime('Impresso %d/%m/%Y %H:%M'))
    d += NL * 4 + CUT

    return Response(d, mimetype='application/octet-stream')
