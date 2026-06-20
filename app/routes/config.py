from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models.motoboy import Motoboy

config_bp = Blueprint('config', __name__, url_prefix='/configuracoes')

def tid():
    return current_user.tenant_id

@config_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    tenant = current_user.tenant
    cfg = tenant.get_settings()

    if request.method == 'POST':
        cfg['whatsapp_notify'] = 'whatsapp_notify' in request.form
        cfg['whatsapp_msg'] = request.form.get('whatsapp_msg', '').strip()
        tenant.save_settings(cfg)
        db.session.commit()
        flash('Configurações salvas.', 'success')
        return redirect(url_for('config.index'))

    motoboys = Motoboy.query.filter_by(tenant_id=tid()).order_by(Motoboy.name).all()
    return render_template('config/index.html', cfg=cfg, motoboys=motoboys)

@config_bp.route('/motoboy/novo', methods=['POST'])
@login_required
def motoboy_novo():
    name  = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    if name:
        db.session.add(Motoboy(tenant_id=tid(), name=name, phone=phone))
        db.session.commit()
        flash(f'Motoboy "{name}" cadastrado.', 'success')
    return redirect(url_for('config.index'))

@config_bp.route('/motoboy/<int:mid>/excluir', methods=['POST'])
@login_required
def motoboy_excluir(mid):
    m = Motoboy.query.filter_by(id=mid, tenant_id=tid()).first_or_404()
    db.session.delete(m)
    db.session.commit()
    flash('Motoboy removido.', 'warning')
    return redirect(url_for('config.index'))
