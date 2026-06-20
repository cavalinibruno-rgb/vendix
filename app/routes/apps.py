from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from app.models.sale import Sale
from app import db
from datetime import datetime, date

apps_bp = Blueprint('apps', __name__, url_prefix='/vendas-apps')

def tid():
    return current_user.tenant_id

@apps_bp.route('/')
@login_required
def index():
    filtro_data  = request.args.get('data', '')
    filtro_mes   = request.args.get('mes',  type=int)
    filtro_ano   = request.args.get('ano',  type=int, default=date.today().year)

    query = Sale.query.filter_by(tenant_id=tid(), status='confirmed', source='app')

    if filtro_data:
        try:
            d = date.fromisoformat(filtro_data)
            query = query.filter(db.func.date(Sale.created_at) == d)
        except ValueError:
            pass
    elif filtro_mes:
        query = query.filter(
            db.extract('month', Sale.created_at) == filtro_mes,
            db.extract('year',  Sale.created_at) == filtro_ano,
        )
    elif filtro_ano:
        query = query.filter(db.extract('year', Sale.created_at) == filtro_ano)

    vendas = query.order_by(Sale.created_at.desc()).all()

    por_app = {}
    for v in vendas:
        nome = v.app_name or 'Sem nome'
        if nome not in por_app:
            por_app[nome] = {'total': 0, 'qtd': 0}
        por_app[nome]['total'] += v.total
        por_app[nome]['qtd']   += 1

    total_geral = sum(v.total for v in vendas)

    meses = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
             'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

    return render_template('apps/index.html',
        vendas=vendas, por_app=por_app, total_geral=total_geral,
        filtro_data=filtro_data, filtro_mes=filtro_mes, filtro_ano=filtro_ano,
        meses=meses,
    )
