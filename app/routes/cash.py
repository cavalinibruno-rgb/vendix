from flask import Blueprint, render_template, redirect, url_for, request, flash
import json
from flask_login import login_required, current_user
from app import db
from app.models.cash import CashRegister
from app.models.sale import Sale
from datetime import datetime
from sqlalchemy import func

cash_bp = Blueprint('cash', __name__, url_prefix='/caixa')

def tid():
    return current_user.tenant_id

def caixa_aberto():
    return CashRegister.query.filter_by(tenant_id=tid(), status='open').first()

def _entra_no_caixa(venda):
    """Vendas de loja sempre entram. Vendas de app só entram se pagas na entrega."""
    if venda.source == 'loja' or venda.source is None:
        return True
    return venda.payment_method in ('entrega_dinheiro', 'entrega_cartao', 'entrega_pix')

@cash_bp.route('/')
@login_required
def index():
    caixa = caixa_aberto()
    historico = CashRegister.query.filter_by(tenant_id=tid(), status='closed')\
                                  .order_by(CashRegister.closed_at.desc()).limit(30).all()
    return render_template('cash/index.html', caixa=caixa, historico=historico)

@cash_bp.route('/abrir', methods=['POST'])
@login_required
def abrir():
    if caixa_aberto():
        flash('Já existe um caixa aberto.', 'warning')
        return redirect(url_for('cash.index'))
    valor = float(request.form.get('opening_amount', 0) or 0)
    caixa = CashRegister(
        tenant_id=tid(),
        opened_by=current_user.id,
        opening_amount=valor,
        status='open',
    )
    db.session.add(caixa)
    db.session.commit()
    flash(f'Caixa aberto com R$ {valor:.2f} de troco inicial.', 'success')
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
    esperado_caixa = caixa.opening_amount + total_dinheiro

    if request.method == 'POST':
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
    diff_total     = total_operador - total_sistema

    vendas = vendas_loja + vendas_app

    return render_template('cash/resumo.html',
        caixa=caixa, vendas=vendas,
        conferencia=conferencia,
        total_sistema=total_sistema,
        total_operador=total_operador,
        diff_total=diff_total,
    )
