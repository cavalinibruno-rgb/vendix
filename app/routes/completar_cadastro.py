from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db

completar_cadastro_bp = Blueprint('completar_cadastro', __name__)


@completar_cadastro_bp.route('/completar-cadastro', methods=['GET', 'POST'])
@login_required
def index():
    if current_user.is_employee or current_user.is_master:
        return redirect(url_for('dashboard.index'))

    tenant = current_user.tenant
    if not tenant:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        tenant.phone        = request.form.get('phone', '').strip()
        tenant.street       = request.form.get('street', '').strip()
        tenant.number       = request.form.get('number', '').strip()
        tenant.neighborhood = request.form.get('neighborhood', '').strip()
        tenant.city         = request.form.get('city', '').strip()
        tenant.state        = request.form.get('state', '').strip().upper()
        tenant.cep          = request.form.get('cep', '').strip()

        if not all([tenant.phone, tenant.street, tenant.number,
                    tenant.neighborhood, tenant.city, tenant.state, tenant.cep]):
            flash('Preencha todos os campos obrigatórios.', 'danger')
            return render_template('completar_cadastro.html', tenant=tenant)

        tenant.profile_complete = True
        db.session.commit()
        return redirect(url_for('dashboard.index'))

    return render_template('completar_cadastro.html', tenant=tenant)
