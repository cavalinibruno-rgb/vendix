from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.tenant import Tenant
from app.models.user import User
from app.models.sale import Sale, SaleItem
from app.models.sale_archive import SaleArchive
from datetime import datetime, timedelta
import json
from werkzeug.security import generate_password_hash
from functools import wraps
import re
import unicodedata

master_bp = Blueprint('master', __name__, url_prefix='/master')

# Preços dos planos (edite aqui conforme necessário)
PRECO_MENSAL = 129.90
PRECO_ANUAL  = 1198.80

def master_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_master:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

@master_bp.route('/')
@login_required
@master_required
def dashboard():
    q = request.args.get('q', '').strip()
    query = Tenant.query
    if q:
        like = f'%{q}%'
        query = query.filter(
            Tenant.store_name.ilike(like) |
            Tenant.email.ilike(like) |
            Tenant.phone.ilike(like)
        )
    tenants = query.order_by(Tenant.created_at.desc()).all()
    return render_template('master/dashboard.html', tenants=tenants, q=q)

@master_bp.route('/tenant/novo', methods=['GET', 'POST'])
@login_required
@master_required
def tenant_novo():
    if request.method == 'POST':
        store_name   = request.form.get('store_name', '').strip()
        email        = request.form.get('email', '').strip().lower()
        phone        = request.form.get('phone', '').strip()
        password     = request.form.get('password', '').strip()
        plan         = request.form.get('plan', 'mensal')
        dias         = int(request.form.get('dias', 30))
        cep          = request.form.get('cep', '').strip()
        street       = request.form.get('street', '').strip()
        number       = request.form.get('number', '').strip()
        neighborhood = request.form.get('neighborhood', '').strip()
        city         = request.form.get('city', '').strip()
        state        = request.form.get('state', '').strip().upper()

        # Gera slug sem acentos ou caracteres especiais
        slug_base = unicodedata.normalize('NFKD', store_name).encode('ascii', 'ignore').decode()
        slug_base = re.sub(r'[^a-z0-9]+', '-', slug_base.lower()).strip('-') or 'loja'
        slug = slug_base
        counter = 1
        while Tenant.query.filter_by(slug=slug).first():
            slug = f'{slug_base}-{counter}'
            counter += 1

        if Tenant.query.filter_by(email=email).first():
            flash('E-mail já cadastrado.', 'danger')
            return render_template('master/tenant_form.html')

        try:
            tenant = Tenant(
                slug=slug,
                store_name=store_name,
                email=email,
                phone=phone,
                plan=plan,
                status='active',
                expires_at=datetime.now() + timedelta(days=dias),
                profile_complete=True,
                cep=cep or None,
                street=street or None,
                number=number or None,
                neighborhood=neighborhood or None,
                city=city or None,
                state=state or None,
            )
            db.session.add(tenant)
            db.session.flush()

            user = User(
                tenant_id=tenant.id,
                username='admin',
                email=email,
                display_name=store_name,
                role='admin'
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f'Loja "{store_name}" criada com sucesso!', 'success')
            return redirect(url_for('master.dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar loja: {str(e)}', 'danger')
            return render_template('master/tenant_form.html')

    return render_template('master/tenant_form.html')

@master_bp.route('/tenant/<int:tenant_id>/suspender')
@login_required
@master_required
def tenant_suspender(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    tenant.status = 'suspended'
    db.session.commit()
    flash(f'Loja "{tenant.store_name}" suspensa.', 'warning')
    return redirect(url_for('master.dashboard'))

@master_bp.route('/tenant/<int:tenant_id>/excluir', methods=['POST'])
@login_required
@master_required
def tenant_excluir(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    nome = tenant.store_name
    try:
        # Remove todos os usuários da loja antes de excluir o tenant
        User.query.filter_by(tenant_id=tenant.id).delete()
        db.session.delete(tenant)
        db.session.commit()
        flash(f'Loja "{nome}" excluída com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir: {str(e)}', 'danger')
    return redirect(url_for('master.dashboard'))

@master_bp.route('/tenant/<int:tenant_id>/ativar', methods=['POST'])
@login_required
@master_required
def tenant_ativar(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    dias = int(request.form.get('dias', 30))
    tenant.status = 'active'
    tenant.expires_at = datetime.now() + timedelta(days=dias)
    db.session.commit()
    flash(f'Loja "{tenant.store_name}" reativada por {dias} dias.', 'success')
    return redirect(url_for('master.dashboard'))


@master_bp.route('/tenant/<int:tenant_id>/adicionar-dias', methods=['POST'])
@login_required
@master_required
def tenant_adicionar_dias(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    dias = int(request.form.get('dias', 30))
    agora = datetime.now()
    base = tenant.expires_at if tenant.expires_at and tenant.expires_at > agora else agora
    tenant.expires_at = base + timedelta(days=dias)
    tenant.status = 'active'
    db.session.commit()
    flash(f'+{dias} dias adicionados para "{tenant.store_name}". Vence em {tenant.expires_at.strftime("%d/%m/%Y")}.', 'success')
    return redirect(url_for('master.dashboard'))


@master_bp.route('/faturamento')
@login_required
@master_required
def faturamento():
    from calendar import month_abbr
    from app.models.pagamento import Pagamento

    all_tenants = Tenant.query.order_by(Tenant.created_at).all()
    hoje = datetime.now()

    mensais_ativos = [t for t in all_tenants if t.plan == 'mensal' and t.is_active]
    anuais_ativos  = [t for t in all_tenants if t.plan == 'anual'  and t.is_active]
    mensais_total  = [t for t in all_tenants if t.plan == 'mensal']
    anuais_total   = [t for t in all_tenants if t.plan == 'anual']
    vencidos       = [t for t in all_tenants if t.status == 'active' and not t.is_active]
    suspensos      = [t for t in all_tenants if t.status == 'suspended']

    mrr = (len(mensais_ativos) * PRECO_MENSAL) + (len(anuais_ativos) * PRECO_ANUAL / 12)
    arr = mrr * 12

    # Pagamentos reais
    todos_pgtos = Pagamento.query.order_by(Pagamento.paid_at.desc()).all()

    # Faturamento do mês atual
    fat_mes_atual = sum(
        float(p.valor) for p in todos_pgtos
        if p.paid_at.year == hoje.year and p.paid_at.month == hoje.month
    )

    # Últimos 12 meses
    meses_labels = []
    meses_novas  = []
    meses_fat    = []

    for i in range(11, -1, -1):
        # calcula ano/mês alvo sem timedelta de 30 dias (evita saltar meses)
        mes = (hoje.month - 1 - i) % 12 + 1
        ano = hoje.year + ((hoje.month - 1 - i) // 12)
        meses_labels.append(f"{month_abbr[mes]}/{str(ano)[2:]}")
        meses_novas.append(sum(
            1 for t in all_tenants
            if t.created_at.year == ano and t.created_at.month == mes
        ))
        meses_fat.append(round(sum(
            float(p.valor) for p in todos_pgtos
            if p.paid_at.year == ano and p.paid_at.month == mes
        ), 2))

    return render_template('master/faturamento.html',
        tenants=all_tenants,
        mensais_ativos=mensais_ativos,
        anuais_ativos=anuais_ativos,
        mensais_total=mensais_total,
        anuais_total=anuais_total,
        vencidos=vencidos,
        suspensos=suspensos,
        mrr=mrr,
        arr=arr,
        fat_mes_atual=fat_mes_atual,
        preco_mensal=PRECO_MENSAL,
        preco_anual=PRECO_ANUAL,
        meses_labels=meses_labels,
        meses_novas=meses_novas,
        meses_fat=meses_fat,
        todos_pgtos=todos_pgtos,
    )


@master_bp.route('/faturamento/registrar', methods=['POST'])
@login_required
@master_required
def registrar_pagamento():
    from app.models.pagamento import Pagamento
    tenant_id = request.form.get('tenant_id', type=int)
    valor     = request.form.get('valor', '').strip().replace(',', '.')
    plano     = request.form.get('plano', 'mensal')
    paid_at   = request.form.get('paid_at', '').strip()
    obs       = request.form.get('observacao', '').strip()

    tenant = Tenant.query.get_or_404(tenant_id)
    try:
        valor_f = float(valor)
    except ValueError:
        flash('Valor inválido.', 'danger')
        return redirect(url_for('master.faturamento'))

    paid_dt = datetime.strptime(paid_at, '%Y-%m-%d') if paid_at else datetime.now()

    p = Pagamento(tenant_id=tenant_id, valor=valor_f, plano=plano,
                  paid_at=paid_dt, observacao=obs or None)
    db.session.add(p)
    db.session.commit()
    flash(f'Pagamento de R$ {valor_f:.2f} registrado para "{tenant.store_name}".', 'success')
    return redirect(url_for('master.faturamento'))


@master_bp.route('/faturamento/excluir/<int:pgto_id>', methods=['POST'])
@login_required
@master_required
def excluir_pagamento(pgto_id):
    from app.models.pagamento import Pagamento
    p = Pagamento.query.get_or_404(pgto_id)
    db.session.delete(p)
    db.session.commit()
    flash('Pagamento removido.', 'warning')
    return redirect(url_for('master.faturamento'))


@master_bp.route('/arquivar-vendas', methods=['POST'])
@login_required
@master_required
def arquivar_vendas():
    """Move vendas com mais de X meses para sales_archive, preservando os itens em JSON."""
    meses = int(request.form.get('meses', 6))
    corte = datetime.now() - timedelta(days=meses * 30)

    vendas = Sale.query.filter(Sale.created_at < corte).all()
    arquivadas = 0
    erros = 0

    for v in vendas:
        try:
            items_data = [
                {
                    'product_id':   item.product_id,
                    'product_name': item.product_name,
                    'unit_price':   item.unit_price,
                    'cost_price':   item.cost_price,
                    'quantity':     item.quantity,
                    'total':        item.total,
                }
                for item in v.items
            ]
            arq = SaleArchive(
                original_id      = v.id,
                tenant_id        = v.tenant_id,
                sale_number      = v.sale_number,
                customer_id      = v.customer_id,
                delivery_mode    = v.delivery_mode,
                delivery_fee     = v.delivery_fee,
                subtotal         = v.subtotal,
                total            = v.total,
                payment_method   = v.payment_method,
                notes            = v.notes,
                status           = v.status,
                source           = v.source,
                app_name         = v.app_name,
                amount_paid      = v.amount_paid,
                discount         = v.discount,
                discount_type    = v.discount_type,
                cashier_name     = v.cashier_name,
                cancelled_at     = v.cancelled_at,
                cancelled_by_name= v.cancelled_by_name,
                cancel_reason    = v.cancel_reason,
                employee_id      = v.employee_id,
                created_at       = v.created_at,
                items_json       = json.dumps(items_data),
            )
            db.session.add(arq)
            # Remove itens e venda original
            for item in v.items:
                db.session.delete(item)
            db.session.delete(v)
            arquivadas += 1
        except Exception:
            db.session.rollback()
            erros += 1
            continue

    db.session.commit()
    return jsonify({
        'arquivadas': arquivadas,
        'erros': erros,
        'corte': corte.strftime('%d/%m/%Y'),
        'meses': meses,
    })


@master_bp.route('/storage-info')
@login_required
@master_required
def storage_info():
    """Informações de armazenamento do banco Postgres."""
    try:
        result = db.session.execute(db.text("""
            SELECT
                pg_size_pretty(pg_database_size(current_database())) AS db_total,
                pg_database_size(current_database()) AS db_bytes,
                (SELECT pg_size_pretty(pg_total_relation_size('sales'))) AS sales_table,
                (SELECT pg_size_pretty(pg_total_relation_size('sale_items'))) AS sale_items_table,
                (SELECT pg_size_pretty(pg_total_relation_size('products'))) AS products_table,
                (SELECT pg_size_pretty(pg_total_relation_size('pedidos_online'))) AS pedidos_table,
                (SELECT COUNT(*) FROM sales) AS total_sales,
                (SELECT COUNT(*) FROM sale_items) AS total_items,
                (
                    SELECT pg_size_pretty(
                        pg_column_size(s.*) +
                        COALESCE((SELECT SUM(pg_column_size(si.*)) FROM sale_items si WHERE si.sale_id = s.id), 0)
                    )
                    FROM sales s ORDER BY s.id DESC LIMIT 1
                ) AS ultima_venda_size,
                (SELECT id FROM sales ORDER BY id DESC LIMIT 1) AS ultima_venda_id
        """)).fetchone()

        # Tamanho de cada tabela principal
        tabelas = db.session.execute(db.text("""
            SELECT
                relname AS tabela,
                pg_size_pretty(pg_total_relation_size(relid)) AS tamanho,
                pg_total_relation_size(relid) AS bytes,
                n_live_tup AS linhas
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
        """)).fetchall()

        return jsonify({
            'banco_total': result.db_total,
            'banco_bytes': result.db_bytes,
            'tabela_sales': result.sales_table,
            'tabela_sale_items': result.sale_items_table,
            'tabela_products': result.products_table,
            'tabela_pedidos': result.pedidos_table,
            'total_vendas': result.total_sales,
            'total_itens': result.total_items,
            'ultima_venda_id': result.ultima_venda_id,
            'ultima_venda_tamanho': result.ultima_venda_size,
            'todas_tabelas': [
                {'tabela': r.tabela, 'tamanho': r.tamanho, 'linhas': r.linhas}
                for r in tabelas
            ],
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
