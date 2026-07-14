from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.ingredient import Ingredient, ProductIngredient
from app.models.product import Product

insumos_bp = Blueprint('insumos', __name__, url_prefix='/insumos')

def _tid():
    return current_user.tenant_id

def _recalcular_custo(ingredient):
    """Recalcula cost_price de todos os produtos que usam este ingrediente."""
    usages = ProductIngredient.query.filter_by(ingredient_id=ingredient.id).all()
    produto_ids = {u.product_id for u in usages}
    for pid in produto_ids:
        produto = Product.query.get(pid)
        if not produto:
            continue
        composicao = ProductIngredient.query.filter_by(product_id=pid).all()
        custo = sum(
            (pi.ingredient.cost_price * pi.quantity)
            for pi in composicao
            if pi.ingredient
        )
        produto.cost_price = round(custo, 2)


@insumos_bp.route('/')
@login_required
def index():
    if not current_user.tenant or not current_user.tenant.is_lanchonete:
        return redirect(url_for('dashboard.index'))
    insumos = Ingredient.query.filter_by(tenant_id=_tid()).order_by(Ingredient.name).all()
    return render_template('insumos/index.html', insumos=insumos)


@insumos_bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if not current_user.tenant or not current_user.tenant.is_lanchonete:
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        unit = request.form.get('unit', 'un').strip() or 'un'
        try:
            cost = round(max(0.0, float(request.form.get('cost_price', 0) or 0)), 2)
        except (TypeError, ValueError):
            cost = 0.0
        if not name:
            flash('Nome é obrigatório.', 'danger')
            return render_template('insumos/form.html', insumo=None)
        ing = Ingredient(tenant_id=_tid(), name=name, unit=unit, cost_price=cost)
        db.session.add(ing)
        db.session.commit()
        flash(f'Insumo "{name}" cadastrado.', 'success')
        return redirect(url_for('insumos.index'))
    return render_template('insumos/form.html', insumo=None)


@insumos_bp.route('/<int:ing_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(ing_id):
    ing = Ingredient.query.filter_by(id=ing_id, tenant_id=_tid()).first_or_404()
    if request.method == 'POST':
        ing.name = request.form.get('name', '').strip() or ing.name
        ing.unit = request.form.get('unit', 'un').strip() or 'un'
        try:
            ing.cost_price = round(max(0.0, float(request.form.get('cost_price', 0) or 0)), 2)
        except (TypeError, ValueError):
            pass
        _recalcular_custo(ing)
        db.session.commit()
        flash('Insumo atualizado. Custo dos produtos recalculado.', 'success')
        return redirect(url_for('insumos.index'))
    return render_template('insumos/form.html', insumo=ing)


@insumos_bp.route('/<int:ing_id>/excluir', methods=['POST'])
@login_required
def excluir(ing_id):
    ing = Ingredient.query.filter_by(id=ing_id, tenant_id=_tid()).first_or_404()
    db.session.delete(ing)
    db.session.commit()
    flash('Insumo excluído.', 'success')
    return redirect(url_for('insumos.index'))


@insumos_bp.route('/api/lista')
@login_required
def api_lista():
    """Retorna todos os insumos da loja para o select do formulário de produto."""
    insumos = Ingredient.query.filter_by(tenant_id=_tid()).order_by(Ingredient.name).all()
    return jsonify([{
        'id': i.id, 'name': i.name, 'unit': i.unit, 'cost_price': i.cost_price
    } for i in insumos])
