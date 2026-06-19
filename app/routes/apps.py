from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.models.sale import Sale
from datetime import datetime, date

apps_bp = Blueprint('apps', __name__, url_prefix='/vendas-apps')

def tid():
    return current_user.tenant_id

@apps_bp.route('/')
@login_required
def index():
    vendas = Sale.query.filter_by(tenant_id=tid(), status='confirmed', source='app')\
                       .order_by(Sale.created_at.desc()).limit(200).all()

    # agrupa por app_name
    por_app = {}
    for v in vendas:
        nome = v.app_name or 'Sem nome'
        if nome not in por_app:
            por_app[nome] = {'vendas': [], 'total': 0, 'qtd': 0}
        por_app[nome]['vendas'].append(v)
        por_app[nome]['total'] += v.total
        por_app[nome]['qtd']   += 1

    total_geral = sum(v.total for v in vendas)

    return render_template('apps/index.html',
        vendas=vendas,
        por_app=por_app,
        total_geral=total_geral,
    )
