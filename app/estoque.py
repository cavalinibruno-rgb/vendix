"""Regras de consumo de estoque compartilhadas por PDV, link de pedidos e cancelamentos.

Cada item vendido consome unidades de um "estoque real":
- produto simples → o próprio produto;
- pack/caixa/maço → o produto unitário pai (pack_qty unidades por pack);
- combo → cada componente (e, se o componente for um pack, o pai dele).
O estoque do combo e o do pack são sempre 0 e nunca são consultados.
"""
from collections import OrderedDict
from app.models.product import Product
from app.models.combo import ComboItem


def alvo_estoque(prod, tenant_id):
    """(produto que tem o estoque real, unidades por item) de um produto não-combo."""
    if prod.pack_parent_id and prod.pack_qty:
        pai = Product.query.filter_by(id=prod.pack_parent_id, tenant_id=tenant_id).first()
        if pai:
            return pai, prod.pack_qty
    return prod, 1


def consumo(prod, qty, tenant_id):
    """Lista de (produto_com_estoque, unidades) que vender `qty` de `prod` consome.
    Os arredondamentos espelham exatamente os das baixas de estoque."""
    comps = ComboItem.query.filter_by(combo_id=prod.id).all()
    if comps:
        out = []
        for ci in comps:
            comp = Product.query.filter_by(id=ci.component_id, tenant_id=tenant_id).first()
            if comp:
                alvo, mult = alvo_estoque(comp, tenant_id)
                out.append((alvo, int(ci.quantity * qty) * mult))
        return out
    alvo, mult = alvo_estoque(prod, tenant_id)
    return [(alvo, int(qty * mult))]


def faltas_estoque(tenant, itens):
    """Valida se há estoque para vender `itens` [(product_id, quantidade, nome)].

    Soma a demanda de todos os itens por estoque real (ex.: 1 caixa c/12 + 5 latas
    da mesma cerveja = 17 latas) e compara com o disponível. Retorna a lista de
    mensagens de falta — vazia quando dá para vender. Lanchonete não controla.
    """
    if tenant is None or tenant.is_lanchonete:
        return []
    demanda = OrderedDict()     # id do estoque real -> [produto, unidades, nomes vendidos]
    for pid, qty, nome in itens:
        if not pid:
            continue
        prod = Product.query.filter_by(id=pid, tenant_id=tenant.id).first()
        if not prod:
            continue
        for alvo, un in consumo(prod, float(qty), tenant.id):
            d = demanda.setdefault(alvo.id, [alvo, 0, []])
            d[1] += un
            if nome not in d[2]:
                d[2].append(nome)
    faltas = []
    for alvo, un, nomes in demanda.values():
        disp = alvo.stock_quantity or 0
        if un > disp:
            via = '' if nomes == [alvo.name] else f' (usado em: {", ".join(nomes)})'
            faltas.append(f'"{alvo.name}": tem {disp}, precisa de {un}{via}')
    return faltas


def disponivel(prod, tenant_id, cache=None):
    """Quantas unidades de `prod` dá para vender agora (para exibir 'Esgotado').
    `cache` opcional: {id: Product} para evitar consultas repetidas."""
    def get(pid):
        if cache is not None and pid in cache:
            return cache[pid]
        p = Product.query.filter_by(id=pid, tenant_id=tenant_id).first()
        if cache is not None:
            cache[pid] = p
        return p
    comps = ComboItem.query.filter_by(combo_id=prod.id).all()
    if comps:
        lim = None
        for ci in comps:
            comp = get(ci.component_id)
            if not comp or not ci.quantity:
                continue
            if comp.pack_parent_id and comp.pack_qty:
                pai = get(comp.pack_parent_id)
                est, por = (pai.stock_quantity or 0) if pai else 0, ci.quantity * comp.pack_qty
            else:
                est, por = comp.stock_quantity or 0, ci.quantity
            n = int(est // por) if por > 0 else 0
            lim = n if lim is None else min(lim, n)
        return lim or 0
    if prod.pack_parent_id and prod.pack_qty:
        pai = get(prod.pack_parent_id)
        return int((pai.stock_quantity or 0) // prod.pack_qty) if pai else 0
    return prod.stock_quantity or 0


def disponibilidade_lote(rows, tenant_id):
    """{product_id: quantas unidades dá para vender} para vários produtos de uma vez.

    `rows`: objetos/linhas com id, stock_quantity, pack_parent_id, pack_qty.
    Usa só 2 consultas extras (componentes dos combos + estoques dos pais),
    evitando uma consulta por produto na listagem do PDV e do link.
    """
    from app import db
    ids = [r.id for r in rows]
    if not ids:
        return {}
    comps = (db.session.query(ComboItem.combo_id, ComboItem.quantity, Product.stock_quantity,
                              Product.pack_parent_id, Product.pack_qty)
             .join(Product, ComboItem.component_id == Product.id)
             .filter(ComboItem.combo_id.in_(ids)).all())
    pais = ({r.pack_parent_id for r in rows if r.pack_parent_id}
            | {c.pack_parent_id for c in comps if c.pack_parent_id})
    est_pai = dict(db.session.query(Product.id, Product.stock_quantity)
                   .filter(Product.id.in_(pais), Product.tenant_id == tenant_id).all()) if pais else {}

    combo_ids, combo = set(), {}
    for combo_id, q, est, pai, pq in comps:
        combo_ids.add(combo_id)
        if pai and pq:
            est, por = est_pai.get(pai) or 0, (q or 0) * pq
        else:
            est, por = est or 0, q or 0
        if por > 0:
            n = int(est // por)
            combo[combo_id] = n if combo_id not in combo else min(combo[combo_id], n)

    out = {}
    for r in rows:
        if r.id in combo_ids:
            out[r.id] = combo.get(r.id, 9999)      # combo sem componente limitante
        elif r.pack_parent_id and r.pack_qty:
            out[r.id] = int((est_pai.get(r.pack_parent_id) or 0) // r.pack_qty)
        else:
            out[r.id] = r.stock_quantity or 0
    return out
