from flask import Blueprint, render_template, redirect, url_for, request, flash
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
        valor_contado = float(request.form.get('closing_amount', 0) or 0)
        notes = request.form.get('notes', '')
        caixa.closing_amount = valor_contado
        caixa.closed_by = current_user.id
        caixa.closed_at = datetime.utcnow()
        caixa.status = 'closed'
        caixa.notes = notes
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
        Sale.created_at <= (caixa.closed_at or datetime.utcnow()),
    ).all()

    vendas = [v for v in todas_vendas if _entra_no_caixa(v)]

    total_dinheiro = sum(v.total for v in vendas if v.payment_method in ('dinheiro', 'entrega_dinheiro'))
    total_cartao   = sum(v.total for v in vendas if v.payment_method in ('cartao', 'entrega_cartao'))
    total_pix      = sum(v.total for v in vendas if v.payment_method in ('pix', 'entrega_pix'))
    total_conta    = sum(v.total for v in vendas if v.payment_method == 'conta')
    total_geral    = sum(v.total for v in vendas)
    esperado_caixa = caixa.opening_amount + total_dinheiro
    diferenca      = (caixa.closing_amount or 0) - esperado_caixa

    return render_template('cash/resumo.html',
        caixa=caixa, vendas=vendas,
        total_dinheiro=total_dinheiro, total_cartao=total_cartao,
        total_pix=total_pix, total_conta=total_conta,
        total_geral=total_geral, esperado_caixa=esperado_caixa,
        diferenca=diferenca,
    )
