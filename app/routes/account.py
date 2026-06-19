from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.account import AccountPayment

account_bp = Blueprint('account', __name__, url_prefix='/conta')

def tid():
    return current_user.tenant_id

@account_bp.route('/')
@login_required
def index():
    clientes = Customer.query.filter_by(tenant_id=tid()).order_by(Customer.name).all()

    # calcula saldo devedor de cada cliente
    devedores = []
    for c in clientes:
        total_conta = sum(
            s.total for s in c.sales
            if s.tenant_id == tid() and s.status == 'confirmed' and s.payment_method == 'conta'
        )
        total_pago = sum(
            p.amount for p in c.payments
            if p.tenant_id == tid()
        )
        saldo = total_conta - total_pago
        if saldo > 0.001:
            devedores.append({'customer': c, 'saldo': saldo})

    devedores.sort(key=lambda x: x['saldo'], reverse=True)
    return render_template('account/index.html', devedores=devedores)

@account_bp.route('/<int:customer_id>')
@login_required
def detalhe(customer_id):
    cliente = Customer.query.filter_by(id=customer_id, tenant_id=tid()).first_or_404()

    vendas_conta = Sale.query.filter_by(
        tenant_id=tid(), customer_id=customer_id,
        payment_method='conta', status='confirmed'
    ).order_by(Sale.created_at.desc()).all()

    pagamentos = AccountPayment.query.filter_by(
        tenant_id=tid(), customer_id=customer_id
    ).order_by(AccountPayment.created_at.desc()).all()

    total_conta = sum(v.total for v in vendas_conta)
    total_pago  = sum(p.amount for p in pagamentos)
    saldo       = total_conta - total_pago

    return render_template('account/detalhe.html',
        cliente=cliente,
        vendas_conta=vendas_conta,
        pagamentos=pagamentos,
        total_conta=total_conta,
        total_pago=total_pago,
        saldo=saldo,
    )

@account_bp.route('/<int:customer_id>/pagar', methods=['POST'])
@login_required
def pagar(customer_id):
    cliente = Customer.query.filter_by(id=customer_id, tenant_id=tid()).first_or_404()
    valor = float(request.form.get('amount', 0) or 0)
    notes = request.form.get('notes', '').strip()

    if valor <= 0:
        flash('Informe um valor válido.', 'danger')
        return redirect(url_for('account.detalhe', customer_id=customer_id))

    pagamento = AccountPayment(
        tenant_id=tid(),
        customer_id=customer_id,
        amount=valor,
        notes=notes,
        created_by=current_user.id,
    )
    db.session.add(pagamento)
    db.session.commit()
    flash(f'Pagamento de R$ {valor:.2f} registrado para {cliente.name}.', 'success')
    return redirect(url_for('account.detalhe', customer_id=customer_id))
