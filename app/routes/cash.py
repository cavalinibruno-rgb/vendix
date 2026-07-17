from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
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
    """Retorna o caixa aberto do operador atual (isolado por operador, não por loja)."""
    uid = current_user.id
    if isinstance(uid, str) and uid.startswith('e_'):
        emp_id = int(uid[2:])
        return CashRegister.query.filter_by(
            tenant_id=tid(), status='open', operator_employee_id=emp_id
        ).first()
    return CashRegister.query.filter(
        CashRegister.tenant_id == tid(),
        CashRegister.status == 'open',
        CashRegister.opened_by == current_user.id,
        CashRegister.operator_employee_id == None,
    ).first()

def _entra_no_caixa(venda, corte=None):
    """Entregas só entram no caixa quando concluídas (motoboy voltou). Retiradas entram imediatamente.
    corte: se informado, entregas só entram se concluídas até esse instante (evita retroatividade)."""
    if venda.delivery_mode == 'entrega':
        if venda.delivered_at is None:
            return False
        if corte and venda.delivered_at > corte:
            return False
        return True
    # retirada: loja entra sempre; app só se pago na entrega
    if venda.source == 'loja' or venda.source is None:
        return True
    return venda.payment_method in (
        'entrega_dinheiro',
        'entrega_cartao', 'entrega_cartao_credito', 'entrega_cartao_debito',
        'entrega_pix',
    )


# Mapa de forma de pagamento → categoria da conferência de caixa
_METODO_CAT = {
    'dinheiro': 'dinheiro', 'entrega_dinheiro': 'dinheiro',
    'cartao_credito': 'credito', 'entrega_cartao_credito': 'credito',
    'cartao': 'credito', 'entrega_cartao': 'credito',
    'cartao_debito': 'debito', 'entrega_cartao_debito': 'debito',
    'pix': 'pix', 'entrega_pix': 'pix',
    'conta': 'conta', 'funcionario': 'funcionario',
}

def _totais_por_categoria(vendas):
    """Soma por categoria (dinheiro/credito/debito/pix/conta/funcionario),
    distribuindo cada parte das vendas COMBINADAS na categoria correta."""
    cats = {'dinheiro': 0.0, 'credito': 0.0, 'debito': 0.0, 'pix': 0.0, 'conta': 0.0, 'funcionario': 0.0}
    for v in vendas:
        if v.payment_method == 'combinado':
            for e in v.payment_entries_list:
                cat = _METODO_CAT.get(e.get('method'))
                if cat:
                    cats[cat] += float(e.get('amount', 0) or 0)
        else:
            cat = _METODO_CAT.get(v.payment_method)
            if cat:
                cats[cat] += v.total
    return cats

@cash_bp.route('/')
@login_required
def index():
    caixa = caixa_aberto()

    # Filtros do histórico
    from datetime import date as _date
    hist_data     = request.args.get('hist_data', '')
    hist_operador = request.args.get('hist_operador', '')
    hist_query = CashRegister.query.filter_by(tenant_id=tid(), status='closed')
    if hist_data:
        try:
            d = _date.fromisoformat(hist_data)
            hist_query = hist_query.filter(func.date(CashRegister.opened_at) == d)
        except ValueError:
            pass
    if hist_operador:
        hist_query = hist_query.filter(CashRegister.operator_name == hist_operador)
    historico = hist_query.order_by(CashRegister.closed_at.desc()).limit(100).all()

    # Operadores distintos no histórico (para dropdown)
    hist_operadores = [r[0] for r in db.session.query(CashRegister.operator_name)
                       .filter(CashRegister.tenant_id == tid(),
                               CashRegister.status == 'closed',
                               CashRegister.operator_name != None,
                               CashRegister.operator_name != '')
                       .distinct().order_by(CashRegister.operator_name).all()]

    # Sobra/falta real de cada caixa = contado - esperado pelo sistema
    historico_diffs = {c.id: _calcular_resumo(c)['diff_total'] for c in historico}
    retiradas = []
    total_retiradas = 0.0
    despesas = []
    total_despesas = 0.0
    if caixa:
        retiradas = CashWithdrawal.query.filter_by(tenant_id=tid(), cash_register_id=caixa.id).all()
        total_retiradas = sum(r.amount for r in retiradas)
        despesas = Expense.query.filter_by(tenant_id=tid(), cash_register_id=caixa.id).order_by(Expense.created_at).all()
        total_despesas = sum(d.amount for d in despesas)

    # Lojista vê todos os caixas abertos; funcionário vê apenas o seu
    uid = current_user.id
    if isinstance(uid, str) and uid.startswith('e_'):
        caixas_abertos = [caixa] if caixa else []
    else:
        caixas_abertos = CashRegister.query.filter_by(
            tenant_id=tid(), status='open'
        ).order_by(CashRegister.opened_at).all()

    return render_template('cash/index.html', caixa=caixa, historico=historico,
                           historico_diffs=historico_diffs,
                           retiradas=retiradas, total_retiradas=total_retiradas,
                           despesas=despesas, total_despesas=total_despesas,
                           caixas_abertos=caixas_abertos,
                           hist_data=hist_data, hist_operador=hist_operador,
                           hist_operadores=hist_operadores,
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

    # O caixa é vinculado ao DONO DAS CREDENCIAIS digitadas no formulário,
    # independente de qual conta está logada no dispositivo:
    # - Credenciais de funcionário: caixa vinculado ao funcionário (ele encontra
    #   o próprio caixa em qualquer dispositivo logado com o login dele)
    # - Credenciais do lojista: caixa próprio do lojista (operator_employee_id None)
    emp_cred = Employee.query.filter_by(tenant_id=tid(), username=username).first()
    if emp_cred and emp_cred.check_password(senha):
        operator_employee_id = emp_cred.id
        # Impede segundo caixa aberto para o mesmo funcionário
        ja_aberto = CashRegister.query.filter_by(
            tenant_id=tid(), status='open', operator_employee_id=emp_cred.id
        ).first()
        if ja_aberto:
            flash(f'Já existe um caixa aberto para {emp_cred.name}.', 'warning')
            return redirect(url_for('cash.index'))
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
        return jsonify({'ok': False, 'error': 'Informe um valor válido.'}), 400
    if not motivo:
        return jsonify({'ok': False, 'error': 'Informe o motivo da retirada.'}), 400

    nome_resp, ok = autenticar_operador(tid(), op_username, op_password)
    if not ok:
        return jsonify({'ok': False, 'error': 'Usuário ou senha incorretos.'}), 400

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
    return jsonify({'ok': True, 'id': w.id})


@cash_bp.route('/retirada/<int:wid>/escpos')
@login_required
def retirada_escpos(wid):
    from flask import Response
    w = CashWithdrawal.query.filter_by(id=wid, tenant_id=tid()).first_or_404()
    store_name = current_user.tenant.store_name or 'Vendix'

    W = 42
    INIT, CP850 = b'\x1b@', b'\x1bt\x02'
    CENTER, LEFT = b'\x1ba\x01', b'\x1ba\x00'
    BON, BOFF = b'\x1bE\x01', b'\x1bE\x00'
    BIG, NORM = b'\x1d!\x11', b'\x1d!\x00'
    CUT, NL = b'\x1dV\x01', b'\n'

    def enc(s):  return s.encode('cp850', errors='replace')
    def ctr(s):  return CENTER + enc(s[:W].center(W)) + NL
    def lft(s):  return LEFT + enc(s[:W]) + NL
    def cols(l, r):
        r = str(r); l = str(l)[:W - len(r) - 1]
        return LEFT + enc(l.ljust(W - len(r)) + r) + NL
    def sep(c='-'): return LEFT + enc(c * W) + NL

    d  = INIT + CP850
    d += CENTER + BON + enc(store_name.upper()[:W].center(W)) + BOFF + NL
    d += sep('=')
    d += ctr('RETIRADA DE CAIXA')
    d += sep('=')
    d += cols('Data',  w.created_at.strftime('%d/%m/%Y'))
    d += cols('Hora',  w.created_at.strftime('%H:%M'))
    d += cols('Operador', (w.operator_name or '-')[:28])
    d += lft(f'Motivo: {w.motivo}')
    d += sep()
    d += CENTER + BIG + BON + enc(f'- R$ {w.amount:.2f}'.center(W // 2)) + NORM + BOFF + NL
    d += sep('=')
    d += NL * 4 + CUT
    return Response(d, mimetype='application/octet-stream')

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

    # Vendas vinculadas a este caixa (multi-caixa). Fallback para caixas antigos (cash_register_id NULL).
    vendas_query = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.cash_register_id == caixa.id,
    )
    if vendas_query.count() == 0:
        # Caixa antigo: sem cash_register_id — usa filtro por período
        todas_vendas = Sale.query.filter(
            Sale.tenant_id == tid(),
            Sale.status == 'confirmed',
            Sale.created_at >= caixa.opened_at,
        ).all()
        vendas = [v for v in todas_vendas if _entra_no_caixa(v)]
    else:
        todas_vendas = vendas_query.all()
        vendas = [v for v in todas_vendas if _entra_no_caixa(v)]

    cats = _totais_por_categoria(vendas)  # inclui as partes das vendas combinadas
    retiradas         = CashWithdrawal.query.filter_by(tenant_id=tid(), cash_register_id=caixa.id).all()
    total_retiradas   = sum(r.amount for r in retiradas)
    despesas          = Expense.query.filter_by(tenant_id=tid(), cash_register_id=caixa.id).all()
    despesas_dinheiro = sum(d.amount for d in despesas if d.payment_method == 'dinheiro')
    despesas_pix      = sum(d.amount for d in despesas if d.payment_method == 'pix')

    total_dinheiro    = cats['dinheiro']
    total_credito     = cats['credito']
    total_debito      = cats['debito']
    total_cartao      = total_credito + total_debito
    total_pix         = cats['pix'] - despesas_pix
    total_conta       = cats['conta']
    total_funcionario = cats['funcionario']
    total_geral       = sum(v.total for v in vendas)
    # Esperado na gaveta = abertura + vendas dinheiro - retiradas - despesas em dinheiro
    esperado_caixa    = caixa.opening_amount + cats['dinheiro'] - total_retiradas - despesas_dinheiro

    # Bloqueia fechamento se há entregas deste caixa pendentes ou em rota
    em_rota = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.delivery_mode == 'entrega',
        Sale.delivered_at == None,
        Sale.cash_register_id == caixa.id,
    ).count()

    if request.method == 'POST':
        if em_rota > 0:
            flash(f'Há {em_rota} entrega(s) pendente(s) ou em rota. Conclua todas antes de fechar o caixa.', 'danger')
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
    # Vendas vinculadas a este caixa (multi-caixa). Fallback para caixas antigos (cash_register_id NULL).
    vendas_query = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.cash_register_id == caixa.id,
    )
    corte = caixa.closed_at or datetime.now()
    if vendas_query.count() == 0:
        # Caixa antigo: sem cash_register_id — usa filtro por período
        todas_vendas = Sale.query.filter(
            Sale.tenant_id == tid(),
            Sale.status == 'confirmed',
            Sale.created_at >= caixa.opened_at,
            Sale.created_at <= corte,
        ).all()
        vendas = [v for v in todas_vendas if _entra_no_caixa(v, corte)]
    else:
        todas_vendas = vendas_query.all()
        vendas = [v for v in todas_vendas if _entra_no_caixa(v, corte)]

    desp  = Expense.query.filter_by(cash_register_id=caixa.id).all()
    desp_din = sum(d.amount for d in desp if d.payment_method == 'dinheiro')
    desp_pix = sum(d.amount for d in desp if d.payment_method == 'pix')
    retiradas       = CashWithdrawal.query.filter_by(cash_register_id=caixa.id).all()
    total_retiradas = sum(r.amount for r in retiradas)

    cats = _totais_por_categoria(vendas)  # inclui as partes das vendas combinadas
    vendas_dinheiro = cats['dinheiro']
    sis = {
        'dinheiro':    caixa.opening_amount + vendas_dinheiro - total_retiradas - desp_din,
        'credito':     cats['credito'],
        'debito':      cats['debito'],
        'pix':         cats['pix'] - desp_pix,
        'conta':       cats['conta'],
        'funcionario': cats['funcionario'],
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
        vendas=vendas,
        conferencia=conferencia,
        total_sistema=total_sistema,
        total_operador=total_operador,
        diff_total=total_operador - total_sistema,
        retiradas=retiradas,
        total_retiradas=total_retiradas,
        # Memória de cálculo do dinheiro esperado na gaveta
        opening_amount=caixa.opening_amount,
        vendas_dinheiro=vendas_dinheiro,
        desp_dinheiro=desp_din,
        dinheiro_esperado=sis['dinheiro'],
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

    # Memória de cálculo do dinheiro esperado na gaveta
    d += lft('DINHEIRO ESPERADO (gaveta)')
    d += cols('  Troco inicial', brl(ctx['opening_amount']))
    d += cols('  + Vendas dinheiro', brl(ctx['vendas_dinheiro']))
    d += cols('  - Sangrias', brl(ctx['total_retiradas']))
    d += cols('  - Despesas dinheiro', brl(ctx['desp_dinheiro']))
    d += cols('  = Esperado', brl(ctx['dinheiro_esperado']))
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
