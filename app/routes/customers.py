from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.customer import Customer, Neighborhood

customers_bp = Blueprint('customers', __name__, url_prefix='/clientes')

def tid():
    return current_user.tenant_id

# ── Clientes ──────────────────────────────────────────

@customers_bp.route('/')
@login_required
def index():
    q = request.args.get('q', '').strip()
    query = Customer.query.filter_by(tenant_id=tid())
    if q:
        query = query.filter(Customer.name.ilike(f'%{q}%') | Customer.phone.ilike(f'%{q}%'))
    customers = query.order_by(Customer.name).all()
    return render_template('customers/index.html', customers=customers, q=q)

@customers_bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    neighborhoods = Neighborhood.query.filter_by(tenant_id=tid()).order_by(Neighborhood.name).all()
    if request.method == 'POST':
        name            = request.form.get('name', '').strip()
        phone           = request.form.get('phone', '').strip()
        cep             = request.form.get('cep', '').strip()
        address         = request.form.get('address', '').strip()
        neighborhood_id = request.form.get('neighborhood_id') or None
        notes           = request.form.get('notes', '').strip()

        if not name:
            flash('Nome é obrigatório.', 'danger')
            return render_template('customers/form.html', neighborhoods=neighborhoods, customer=None)

        # Pega taxa do bairro
        fee = 0
        if neighborhood_id:
            n = Neighborhood.query.get(neighborhood_id)
            if n:
                fee = n.delivery_fee

        customer = Customer(
            tenant_id=tid(),
            name=name, phone=phone, cep=cep, address=address,
            neighborhood_id=neighborhood_id,
            delivery_fee=fee, notes=notes
        )
        db.session.add(customer)
        db.session.commit()
        flash(f'Cliente "{name}" cadastrado!', 'success')
        return redirect(url_for('customers.index'))

    return render_template('customers/form.html', neighborhoods=neighborhoods, customer=None)

@customers_bp.route('/<int:customer_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(customer_id):
    customer      = Customer.query.filter_by(id=customer_id, tenant_id=tid()).first_or_404()
    neighborhoods = Neighborhood.query.filter_by(tenant_id=tid()).order_by(Neighborhood.name).all()
    if request.method == 'POST':
        customer.name            = request.form.get('name', '').strip()
        customer.phone           = request.form.get('phone', '').strip()
        customer.cep             = request.form.get('cep', '').strip()
        customer.address         = request.form.get('address', '').strip()
        customer.neighborhood_id = request.form.get('neighborhood_id') or None
        customer.notes           = request.form.get('notes', '').strip()
        if customer.neighborhood_id:
            n = Neighborhood.query.get(customer.neighborhood_id)
            if n:
                customer.delivery_fee = n.delivery_fee
        db.session.commit()
        flash('Cliente atualizado!', 'success')
        return redirect(url_for('customers.index'))
    return render_template('customers/form.html', neighborhoods=neighborhoods, customer=customer)

@customers_bp.route('/<int:customer_id>/excluir', methods=['POST'])
@login_required
def excluir(customer_id):
    customer = Customer.query.filter_by(id=customer_id, tenant_id=tid()).first_or_404()
    db.session.delete(customer)
    db.session.commit()
    flash('Cliente removido.', 'success')
    return redirect(url_for('customers.index'))

# ── Bairros ───────────────────────────────────────────

@customers_bp.route('/bairros')
@login_required
def bairros():
    neighborhoods = Neighborhood.query.filter_by(tenant_id=tid()).order_by(Neighborhood.name).all()
    return render_template('customers/bairros.html', neighborhoods=neighborhoods)

@customers_bp.route('/bairros/novo', methods=['POST'])
@login_required
def bairro_novo():
    name = request.form.get('name', '').strip()
    fee  = float(request.form.get('delivery_fee', 0) or 0)
    if name:
        n = Neighborhood(tenant_id=tid(), name=name, delivery_fee=fee)
        db.session.add(n)
        db.session.commit()
        flash(f'Bairro "{name}" cadastrado!', 'success')
    return redirect(url_for('customers.bairros'))

@customers_bp.route('/bairros/criar-ajax', methods=['POST'])
@login_required
def bairro_criar_ajax():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    try:
        fee = float(data.get('fee', 0) or 0)
    except (ValueError, TypeError):
        fee = 0
    if not name:
        return jsonify({'error': 'Nome do bairro é obrigatório.'}), 400
    # Evita duplicar bairro com mesmo nome
    existente = Neighborhood.query.filter_by(tenant_id=tid()).filter(
        db.func.lower(Neighborhood.name) == name.lower()
    ).first()
    if existente:
        return jsonify({'id': existente.id, 'name': existente.name, 'fee': existente.delivery_fee})
    n = Neighborhood(tenant_id=tid(), name=name, delivery_fee=fee)
    db.session.add(n)
    db.session.commit()
    return jsonify({'id': n.id, 'name': n.name, 'fee': n.delivery_fee})

@customers_bp.route('/bairros/<int:bairro_id>/editar', methods=['POST'])
@login_required
def bairro_editar(bairro_id):
    n = Neighborhood.query.filter_by(id=bairro_id, tenant_id=tid()).first_or_404()
    n.name         = request.form.get('name', '').strip()
    n.delivery_fee = float(request.form.get('delivery_fee', 0) or 0)
    db.session.commit()
    flash('Bairro atualizado!', 'success')
    return redirect(url_for('customers.bairros'))

@customers_bp.route('/bairros/<int:bairro_id>/excluir', methods=['POST'])
@login_required
def bairro_excluir(bairro_id):
    n = Neighborhood.query.filter_by(id=bairro_id, tenant_id=tid()).first_or_404()
    db.session.delete(n)
    db.session.commit()
    flash('Bairro removido.', 'success')
    return redirect(url_for('customers.bairros'))

# ── API bairros ───────────────────────────────────────
@customers_bp.route('/bairros/api')
@login_required
def api_bairros():
    neighborhoods = Neighborhood.query.filter_by(tenant_id=tid()).order_by(Neighborhood.name).all()
    return jsonify([{'id': n.id, 'name': n.name, 'delivery_fee': n.delivery_fee} for n in neighborhoods])

# ── API criar cliente (rápido, na Nova Venda) ─────────
@customers_bp.route('/api/criar', methods=['POST'])
@login_required
def api_criar():
    data = request.get_json() or {}
    name  = (data.get('name') or '').strip()
    phone = (data.get('phone') or '').strip()
    cep   = (data.get('cep') or '').strip()
    address = (data.get('address') or '').strip()
    neighborhood_id = data.get('neighborhood_id') or None
    if not name:
        return jsonify({'error': 'Nome é obrigatório.'}), 400

    fee = 0
    if neighborhood_id:
        n = Neighborhood.query.filter_by(id=neighborhood_id, tenant_id=tid()).first()
        if n:
            fee = n.delivery_fee
        else:
            neighborhood_id = None

    c = Customer(
        tenant_id=tid(), name=name, phone=phone, cep=cep,
        address=address, neighborhood_id=neighborhood_id, delivery_fee=fee,
    )
    db.session.add(c)
    db.session.commit()
    return jsonify({
        'id': c.id,
        'name': c.name,
        'phone': c.phone or '',
        'address': c.address or '',
        'neighborhood_id': c.neighborhood_id,
        'neighborhood_name': c.neighborhood.name if c.neighborhood else '',
        'delivery_fee': c.delivery_fee or 0,
    })

# ── API busca clientes ────────────────────────────────
@customers_bp.route('/api/buscar')
@login_required
def api_buscar():
    q = request.args.get('q', '')
    customers = Customer.query.filter_by(tenant_id=tid()).filter(
        Customer.name.ilike(f'%{q}%') | Customer.phone.ilike(f'%{q}%')
    ).limit(10).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'phone': c.phone or '',
        'address': c.address or '',
        'neighborhood_id': c.neighborhood_id,
        'neighborhood_name': c.neighborhood.name if c.neighborhood else '',
        'delivery_fee': c.delivery_fee or 0,
    } for c in customers])
