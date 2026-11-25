"""Empresa com filiais: troca de loja do dono e criação de filial."""
import re
import unicodedata
from datetime import datetime, timedelta
from flask import Blueprint, redirect, url_for, request, flash, session
from flask_login import login_required, current_user
from app import db
from app.models.tenant import Tenant

empresa_bp = Blueprint('empresa', __name__, url_prefix='/empresa')


def _matriz_do_dono():
    """Loja principal do dono logado (None para funcionário/master)."""
    if not current_user.is_authenticated or current_user.is_master or current_user.is_employee:
        return None
    if current_user.role != 'admin':
        return None
    return Tenant.query.get(getattr(current_user, 'matriz_id', None) or current_user.tenant_id)


@empresa_bp.route('/trocar/<int:loja_id>', methods=['POST'])
@login_required
def trocar(loja_id):
    matriz = _matriz_do_dono()
    if matriz is None:
        return redirect(url_for('dashboard.index'))
    if loja_id == matriz.id:
        session.pop('loja_ativa', None)
    else:
        filial = Tenant.query.get(loja_id)
        if not filial or filial.matriz_id != matriz.id:
            flash('Loja não encontrada.', 'danger')
            return redirect(url_for('dashboard.index'))
        if not filial.is_active:
            flash(f'A assinatura da filial "{filial.store_name}" está vencida. Renove para acessar.', 'warning')
            return redirect(url_for('dashboard.index'))
        session['loja_ativa'] = filial.id
    return redirect(url_for('dashboard.index'))


def _slug_unico(nome):
    from sqlalchemy import func as _f
    base = unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode()
    base = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-') or 'loja'
    slug, n = base, 1
    while Tenant.query.filter((Tenant.slug == slug) |
                              (_f.replace(Tenant.slug, '-', '') == slug.replace('-', ''))).first():
        slug = f'{base}-{n}'
        n += 1
    return slug


def criar_filial(matriz, nome, copiar_produtos, plano='mensal', dias=30):
    """Cria a filial ligada à matriz. Não faz commit (quem chama decide)."""
    from app.seed import seed_categorias_nativas
    slug = _slug_unico(nome)
    filial = Tenant(
        slug=slug, store_name=nome,
        email=f'filial-{slug}@filiais.vendixapp.com.br',   # placeholder único; o login é o do dono
        phone=matriz.phone, plan=plano, status='active',
        business_type=matriz.business_type,
        expires_at=datetime.now() + timedelta(days=dias),
        profile_complete=True, matriz_id=matriz.id,
        cep=matriz.cep, street=matriz.street, number=matriz.number,
        neighborhood=matriz.neighborhood, city=matriz.city, state=matriz.state,
    )
    db.session.add(filial)
    db.session.flush()
    seed_categorias_nativas(filial.id)
    db.session.flush()
    if copiar_produtos:
        copiar_catalogo(matriz.id, filial.id)
    return filial


def copiar_catalogo(origem_id, destino_id):
    """Copia categorias, marcas e produtos (com packs e combos) com ESTOQUE ZERADO."""
    from app.models.product import Product, ProductType, Brand
    from app.models.combo import ComboItem

    tipos_dest = {t.name.lower(): t for t in ProductType.query.filter_by(tenant_id=destino_id).all()}
    mapa_tipo = {}
    for t in ProductType.query.filter_by(tenant_id=origem_id).all():
        novo = tipos_dest.get(t.name.lower())
        if novo is None:
            novo = ProductType(tenant_id=destino_id, name=t.name, type_number=t.type_number,
                               protected=t.protected, sort_order=t.sort_order)
            db.session.add(novo)
            db.session.flush()
        mapa_tipo[t.id] = novo.id

    mapa_marca = {}
    for b in Brand.query.filter_by(tenant_id=origem_id).all():
        nova = Brand(tenant_id=destino_id, name=b.name, brand_number=b.brand_number)
        db.session.add(nova)
        db.session.flush()
        mapa_marca[b.id] = nova.id

    copiar = ['product_number', 'name', 'description', 'sale_price', 'sale_price_card', 'sale_price_event',
              'sale_price_cold', 'sale_price_cold_card', 'cost_price', 'min_stock', 'active', 'online_active',
              'disponivel', 'image_path', 'image_url', 'image_data', 'image_mime', 'thumbnail_data',
              'sort_order', 'pack_qty', 'promo_starts_at', 'promo_ends_at', 'addons']
    origem = Product.query.filter_by(tenant_id=origem_id).all()
    mapa_prod = {}
    for p in origem:
        novo = Product(tenant_id=destino_id, stock_quantity=0,
                       type_id=mapa_tipo.get(p.type_id), brand_id=mapa_marca.get(p.brand_id),
                       **{c: getattr(p, c) for c in copiar})
        db.session.add(novo)
        db.session.flush()
        mapa_prod[p.id] = novo
    for p in origem:                                   # packs apontam para o pai copiado
        if p.pack_parent_id and p.pack_parent_id in mapa_prod:
            mapa_prod[p.id].pack_parent_id = mapa_prod[p.pack_parent_id].id
    ids = list(mapa_prod)
    if ids:
        for c in ComboItem.query.filter(ComboItem.combo_id.in_(ids)).all():
            if c.combo_id in mapa_prod and c.component_id in mapa_prod:
                db.session.add(ComboItem(combo_id=mapa_prod[c.combo_id].id,
                                         component_id=mapa_prod[c.component_id].id,
                                         quantity=c.quantity))
    return len(origem)


def _periodo(chave, de_txt=None, ate_txt=None):
    hoje = datetime.combine(datetime.now().date(), datetime.min.time())
    agora = datetime.now()
    if chave == '7d':
        return hoje - timedelta(days=6), agora, 'Últimos 7 dias'
    if chave == 'mes':
        return hoje.replace(day=1), agora, 'Este mês'
    if chave == 'mes_passado':
        fim = hoje.replace(day=1) - timedelta(seconds=1)
        return fim.replace(day=1, hour=0, minute=0, second=0), fim, 'Mês passado'
    if chave == 'periodo':
        try:
            ini = datetime.strptime(de_txt, '%Y-%m-%d')
            fim = datetime.strptime(ate_txt, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
            return ini, fim, f'{ini:%d/%m/%Y} a {fim:%d/%m/%Y}'
        except (TypeError, ValueError):
            pass
    return hoje, agora, 'Hoje'


def _numeros_loja(loja_id, ini, fim):
    from sqlalchemy import func
    from app.models.sale import Sale, SaleItem
    q = Sale.query.filter(Sale.tenant_id == loja_id, Sale.status == 'confirmed',
                          Sale.created_at >= ini, Sale.created_at <= fim)
    fat, pedidos = q.with_entities(func.coalesce(func.sum(Sale.total), 0.0), func.count(Sale.id)).first()
    receita = q.with_entities(func.coalesce(func.sum(Sale.subtotal - func.coalesce(Sale.discount, 0)), 0.0)).scalar()
    custo = (db.session.query(func.coalesce(func.sum(SaleItem.cost_price * SaleItem.quantity), 0.0))
             .join(Sale, SaleItem.sale_id == Sale.id)
             .filter(Sale.tenant_id == loja_id, Sale.status == 'confirmed',
                     Sale.created_at >= ini, Sale.created_at <= fim).scalar())
    fat, pedidos, receita, custo = float(fat or 0), int(pedidos or 0), float(receita or 0), float(custo or 0)
    return {'faturamento': fat, 'pedidos': pedidos, 'ticket': fat / pedidos if pedidos else 0.0,
            'lucro': receita - custo, 'receita': receita}


@empresa_bp.route('/visao')
@login_required
def visao():
    """Faturamento de cada loja da empresa e o total juntando todas."""
    from flask import render_template
    matriz = _matriz_do_dono()
    if matriz is None:
        return redirect(url_for('dashboard.index'))
    chave = request.args.get('periodo', 'hoje')
    ini, fim, rotulo = _periodo(chave, request.args.get('de'), request.args.get('ate'))
    linhas = []
    for loja in matriz.lojas_da_empresa():
        n = _numeros_loja(loja.id, ini, fim)
        n['loja'] = loja
        linhas.append(n)
    tot = {k: sum(l[k] for l in linhas) for k in ('faturamento', 'pedidos', 'lucro', 'receita')}
    tot['ticket'] = tot['faturamento'] / tot['pedidos'] if tot['pedidos'] else 0.0
    for l in linhas:
        l['part'] = (l['faturamento'] / tot['faturamento'] * 100) if tot['faturamento'] else 0.0
    return render_template('empresa/visao.html', linhas=linhas, tot=tot, chave=chave, rotulo=rotulo,
                           de=request.args.get('de', ''), ate=request.args.get('ate', ''))
