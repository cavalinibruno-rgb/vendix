from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.vale import Employee, Vale
from app.models.motoboy import Motoboy
from datetime import date, datetime

vale_bp = Blueprint('vale', __name__, url_prefix='/vale')

def tid():
    return current_user.tenant_id

@vale_bp.route('/')
@login_required
def index():
    mes  = request.args.get('mes',  type=int, default=date.today().month)
    ano  = request.args.get('ano',  type=int, default=date.today().year)

    employees = Employee.query.filter_by(tenant_id=tid()).order_by(Employee.name).all()

    # Total de vale por funcionário no mês selecionado
    totais = {}
    for e in employees:
        total = sum(v.amount for v in e.vales if v.date.month == mes and v.date.year == ano)
        totais[e.id] = total

    total_geral = sum(totais.values())

    meses = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
             'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

    motoboys = Motoboy.query.filter_by(tenant_id=tid(), active=True).order_by(Motoboy.name).all()

    return render_template('vale/index.html',
        employees=employees, totais=totais, total_geral=total_geral,
        mes=mes, ano=ano, meses=meses, motoboys=motoboys,
    )

@vale_bp.route('/api/funcionarios')
@login_required
def api_funcionarios():
    employees = Employee.query.filter_by(tenant_id=tid()).order_by(Employee.name).all()
    return jsonify([{'id': e.id, 'name': e.name, 'role': e.role} for e in employees])

@vale_bp.route('/funcionario/novo', methods=['POST'])
@login_required
def funcionario_novo():
    name = request.form.get('name', '').strip()
    role = request.form.get('role', 'caixa')
    if role not in ('caixa', 'motoboy'):
        role = 'caixa'
    if name:
        e = Employee(tenant_id=tid(), name=name, role=role)
        db.session.add(e)
        db.session.flush()
        # Sincroniza com tabela motoboys para aparecer no despacho
        if role == 'motoboy':
            db.session.add(Motoboy(tenant_id=tid(), name=name))
        db.session.commit()
        flash(f'Funcionário "{name}" cadastrado!', 'success')
    return redirect(url_for('vale.index'))

@vale_bp.route('/funcionario/<int:emp_id>/credenciais', methods=['POST'])
@login_required
def funcionario_credenciais(emp_id):
    e = Employee.query.filter_by(id=emp_id, tenant_id=tid(), role='caixa').first_or_404()
    username = request.form.get('username', '').strip()
    senha    = request.form.get('senha', '').strip()
    if not username or not senha:
        flash('Informe usuário e senha.', 'danger')
        return redirect(url_for('vale.index'))
    if len(senha) < 8:
        flash('A senha deve ter pelo menos 8 caracteres.', 'danger')
        return redirect(url_for('vale.index'))
    # Garante username único no tenant
    conflict = Employee.query.filter_by(tenant_id=tid(), username=username).filter(Employee.id != emp_id).first()
    if conflict:
        flash(f'O usuário "{username}" já está em uso por outro funcionário.', 'danger')
        return redirect(url_for('vale.index'))
    e.username = username
    e.set_password(senha)
    db.session.commit()
    flash(f'Credenciais de "{e.name}" salvas.', 'success')
    return redirect(url_for('vale.index'))

@vale_bp.route('/funcionario/<int:emp_id>/excluir', methods=['POST'])
@login_required
def funcionario_excluir(emp_id):
    e = Employee.query.filter_by(id=emp_id, tenant_id=tid()).first_or_404()
    if e.role == 'motoboy':
        m = Motoboy.query.filter_by(tenant_id=tid(), name=e.name).first()
        if m:
            m.active = False  # desativa para não quebrar FK de vendas existentes
    db.session.delete(e)
    db.session.commit()
    flash('Funcionário removido.', 'success')
    return redirect(url_for('vale.index'))

@vale_bp.route('/funcionario/<int:emp_id>')
@login_required
def funcionario_detalhe(emp_id):
    e   = Employee.query.filter_by(id=emp_id, tenant_id=tid()).first_or_404()
    mes = request.args.get('mes', type=int, default=date.today().month)
    ano = request.args.get('ano', type=int, default=date.today().year)

    vales = [v for v in e.vales if v.date.month == mes and v.date.year == ano]
    vales.sort(key=lambda v: v.date)
    total = sum(v.amount for v in vales)

    meses = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
             'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

    return render_template('vale/detalhe.html',
        employee=e, vales=vales, total=total,
        mes=mes, ano=ano, meses=meses,
    )

@vale_bp.route('/funcionario/<int:emp_id>/novo', methods=['POST'])
@login_required
def vale_novo(emp_id):
    e = Employee.query.filter_by(id=emp_id, tenant_id=tid()).first_or_404()
    amount_str = request.form.get('amount', '0').replace(',', '.').strip()
    try:
        amount = float(amount_str)
    except ValueError:
        amount = 0
    date_str = request.form.get('date', '')
    try:
        vale_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        vale_date = date.today()
    notes = request.form.get('notes', '').strip()

    if amount > 0:
        v = Vale(tenant_id=tid(), employee_id=e.id, amount=amount,
                 date=vale_date, notes=notes)
        db.session.add(v)
        db.session.commit()
        flash(f'Vale de R$ {amount:.2f} lançado para {e.name}.', 'success')
    return redirect(url_for('vale.funcionario_detalhe', emp_id=emp_id,
                            mes=vale_date.month, ano=vale_date.year))

@vale_bp.route('/vale/<int:vale_id>/excluir', methods=['POST'])
@login_required
def vale_excluir(vale_id):
    v = Vale.query.filter_by(id=vale_id, tenant_id=tid()).first_or_404()
    emp_id = v.employee_id
    mes, ano = v.date.month, v.date.year
    db.session.delete(v)
    db.session.commit()
    flash('Vale removido.', 'success')
    return redirect(url_for('vale.funcionario_detalhe', emp_id=emp_id, mes=mes, ano=ano))

@vale_bp.route('/motoboy/novo', methods=['POST'])
@login_required
def motoboy_novo():
    name  = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    if name:
        db.session.add(Motoboy(tenant_id=tid(), name=name, phone=phone))
        db.session.commit()
        flash(f'Motoboy "{name}" cadastrado.', 'success')
    return redirect(url_for('vale.index'))

@vale_bp.route('/motoboy/<int:mid>/excluir', methods=['POST'])
@login_required
def motoboy_excluir(mid):
    m = Motoboy.query.filter_by(id=mid, tenant_id=tid()).first_or_404()
    m.active = False
    db.session.commit()
    flash('Motoboy removido.', 'warning')
    return redirect(url_for('vale.index'))
