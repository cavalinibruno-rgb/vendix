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
        opened_by            = current_user.id,
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

    total_dinheiro = sum(v.total for v in vendas if v.payment_method in ('dinheiro', 'entrega_dinheiro'))
    total_cartao   = sum(v.total for v in vendas if v.payment_method in ('cartao', 'entrega_cartao'))
    total_pix      = sum(v.total for v in vendas if v.payment_method in ('pix', 'entrega_pix'))
    total_conta    = sum(v.total for v in vendas if v.payment_method == 'conta')
    total_geral    = sum(v.total for v in vendas)
    retiradas      = CashWithdrawal.query.filter_by(tenant_id=tid(), cash_register_id=caixa.id).all()
    total_retiradas = sum(r.amount for r in retiradas)
    esperado_caixa = caixa.opening_amount + total_dinheiro - total_retiradas

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
            'loja_dinheiro': fval('loja_dinheiro'),
            'loja_cartao':   fval('loja_cartao'),
            'loja_pix':      fval('loja_pix'),
            'loja_conta':    fval('loja_conta'),
            'app_dinheiro':  fval('app_dinheiro'),
            'app_cartao':    fval('app_cartao'),
            'app_pix':       fval('app_pix'),
        }
        total_operador = sum(op.values())
        caixa.closing_amount = total_operador
        caixa.closing_data   = json.dumps(op)
        caixa.closed_by      = current_user.id
        caixa.closed_at      = datetime.now()
        caixa.status         = 'closed'
        caixa.notes          = request.form.get('notes', '')
        db.session.commit()
        flash('Caixa fechado com sucesso!', 'success')
        return redirect(url_for('cash.resumo', caixa_id=caixa.id))

    return render_template('cash/fechar.html',
        caixa=caixa, vendas=vendas,
        total_dinheiro=total_dinheiro, total_cartao=total_cartao,
        total_pix=total_pix, total_conta=total_conta,
        total_geral=total_geral, esperado_caixa=esperado_caixa,
        retiradas=retiradas, total_retiradas=total_retiradas,
        em_rota=em_rota,
    )

@cash_bp.route('/<int:caixa_id>/resumo')
@login_required
def resumo(caixa_id):
    caixa = CashRegister.query.filter_by(id=caixa_id, tenant_id=tid()).first_or_404()

    todas_vendas = Sale.query.filter(
        Sale.tenant_id == tid(),
        Sale.status == 'confirmed',
        Sale.created_at >= caixa.opened_at,
        Sale.created_at <= (caixa.closed_at or datetime.now()),
    ).all()

    vendas_loja = [v for v in todas_vendas if v.source != 'app' and v.status == 'confirmed']
    vendas_app  = [v for v in todas_vendas if v.source == 'app'  and v.status == 'confirmed']

    def tot(lst, methods): return sum(v.total for v in lst if v.payment_method in methods)

    sis = {
        'loja_dinheiro': tot(vendas_loja, ('dinheiro', 'entrega_dinheiro')),
        'loja_cartao':   tot(vendas_loja, ('cartao',   'entrega_cartao')),
        'loja_pix':      tot(vendas_loja, ('pix',      'entrega_pix')),
        'loja_conta':    tot(vendas_loja, ('conta',)),
        'app_dinheiro':  tot(vendas_app,  ('dinheiro', 'entrega_dinheiro')),
        'app_cartao':    tot(vendas_app,  ('cartao',   'entrega_cartao')),
        'app_pix':       tot(vendas_app,  ('pix',      'entrega_pix')),
    }

    op = json.loads(caixa.closing_data) if caixa.closing_data else {k: 0 for k in sis}

    retiradas       = CashWithdrawal.query.filter_by(cash_register_id=caixa.id).all()
    total_retiradas = sum(r.amount for r in retiradas)

    # Desconta retiradas do dinheiro esperado pelo sistema (saem do caixa físico)
    sis['loja_dinheiro'] = max(0, sis['loja_dinheiro'] - total_retiradas)

    conferencia = []
    for key, label, icon, color in [
        ('loja_dinheiro', 'Loja — Dinheiro', 'bi-cash',             'text-success'),
        ('loja_cartao',   'Loja — Cartão',   'bi-credit-card',      'text-primary'),
        ('loja_pix',      'Loja — Pix',      'bi-qr-code',          'text-info'),
        ('loja_conta',    'Loja — Conta',    'bi-person-lines-fill','text-warning'),
        ('app_dinheiro',  'App — Dinheiro',  'bi-cash',             'text-success'),
        ('app_cartao',    'App — Cartão',    'bi-credit-card',      'text-primary'),
        ('app_pix',       'App — Pix',       'bi-qr-code',          'text-info'),
    ]:
        s = sis.get(key, 0)
        o = op.get(key, 0)
        diff = o - s
        conferencia.append({'label': label, 'icon': icon, 'color': color,
                            'sistema': s, 'operador': o, 'diff': diff})

    total_sistema  = sum(sis.values())
    total_operador = sum(op.values())
    diff_total      = total_operador - total_sistema

    vendas = vendas_loja + vendas_app

    return render_template('cash/resumo.html',
        caixa=caixa, vendas=vendas,
        conferencia=conferencia,
        total_sistema=total_sistema,
        total_operador=total_operador,
        diff_total=diff_total,
        retiradas=retiradas,
        total_retiradas=total_retiradas,
    )
