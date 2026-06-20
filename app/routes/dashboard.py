from flask import Blueprint, render_template, request, redirect, url_for, session
from flask_login import login_required, current_user
from app.models.tenant import Tenant
from app.models.sale import Sale
from app.models.cash import CashRegister
from app.models.user import User
from datetime import datetime, date

dashboard_bp = Blueprint('dashboard', __name__)

def require_active_tenant(f):
    from functools import wraps
    from flask import redirect, url_for, flash
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.is_master:
            return f(*args, **kwargs)
        tenant = Tenant.query.get(current_user.tenant_id)
        if not tenant or not tenant.is_active:
            flash('Sua assinatura está suspensa.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

@dashboard_bp.route('/')
@login_required
@require_active_tenant
def index():
    tenant = Tenant.query.get(current_user.tenant_id)
    tid = current_user.tenant_id

    hoje_inicio = datetime.combine(date.today(), datetime.min.time())

    todas_hoje = Sale.query.filter(
        Sale.tenant_id == tid,
        Sale.status == 'confirmed',
        Sale.created_at >= hoje_inicio,
    ).all()

    def entra_no_caixa(v):
        if v.source == 'loja' or v.source is None:
            return True
        return v.payment_method in ('entrega_dinheiro', 'entrega_cartao', 'entrega_pix')

    vendas_hoje = [v for v in todas_hoje if entra_no_caixa(v)]

    total_dinheiro = sum(v.total for v in vendas_hoje if v.payment_method in ('dinheiro', 'entrega_dinheiro'))
    total_cartao   = sum(v.total for v in vendas_hoje if v.payment_method in ('cartao', 'entrega_cartao'))
    total_pix      = sum(v.total for v in vendas_hoje if v.payment_method in ('pix', 'entrega_pix'))
    total_conta    = sum(v.total for v in vendas_hoje if v.payment_method == 'conta')
    total_geral    = sum(v.total for v in vendas_hoje)

    caixa = CashRegister.query.filter_by(tenant_id=tid, status='open').first()

    ultimas_vendas = Sale.query.filter_by(tenant_id=tid, status='confirmed')\
                               .order_by(Sale.created_at.desc()).limit(10).all()

    cfg = tenant.get_settings()
    modo_restrito = (
        cfg.get('dashboard_operador_restrito') and
        caixa is not None and
        caixa.operator_employee_id is not None
    )

    # Quando caixa fechado, exige senha do dono para ver valores
    desbloqueado = caixa is not None or session.get('dashboard_desbloqueado', False)
    senha_erro = session.pop('dashboard_erro', False)

    return render_template('dashboard/index.html',
        tenant=tenant,
        qtd_vendas=len(vendas_hoje),
        total_dinheiro=total_dinheiro,
        total_cartao=total_cartao,
        total_pix=total_pix,
        total_conta=total_conta,
        total_geral=total_geral,
        caixa=caixa,
        ultimas_vendas=ultimas_vendas,
        modo_restrito=modo_restrito,
        desbloqueado=desbloqueado,
        senha_erro=senha_erro,
    )

@dashboard_bp.route('/dashboard/desbloquear', methods=['POST'])
@login_required
def desbloquear():
    senha = request.form.get('senha', '')
    user = User.query.get(current_user.id)
    if user and user.check_password(senha):
        session['dashboard_desbloqueado'] = True
    else:
        session['dashboard_desbloqueado'] = False
        session['dashboard_erro'] = True
    return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/dashboard/bloquear')
@login_required
def bloquear():
    session.pop('dashboard_desbloqueado', None)
    return redirect(url_for('dashboard.index'))
