"""Dados do Dashboard do visual novo (proposta B), calculados com consultas agregadas."""
import json
from datetime import datetime, date, timedelta
from sqlalchemy import func
from app import db
from app.models.sale import Sale, SaleItem
from app.models.product import Product
from app.models.combo import ComboItem
from app.models.pedido_online import PedidoOnline

DIAS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho',
         'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']

# forma de pagamento gravada → grupo exibido
GRUPOS_PGTO = {
    'pix': 'Pix', 'entrega_pix': 'Pix',
    'dinheiro': 'Dinheiro', 'entrega_dinheiro': 'Dinheiro',
    'cartao_credito': 'Crédito', 'entrega_cartao_credito': 'Crédito', 'cartao': 'Crédito', 'entrega_cartao': 'Crédito',
    'cartao_debito': 'Débito', 'entrega_cartao_debito': 'Débito',
    'conta': 'Fiado', 'funcionario': 'Funcionário',
}
CORES_PGTO = {'Pix': '#14161c', 'Dinheiro': '#d9ad52', 'Crédito': '#6b7387', 'Débito': '#c3c8d3',
              'Fiado': '#b4532a', 'Funcionário': '#8a7fc0', 'Outros': '#e3e5ea'}


def brl(v):
    s = f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return 'R$ ' + s


def _janela(periodo, agora):
    hoje = datetime.combine(agora.date(), datetime.min.time())
    if periodo == '7d':
        ini = hoje - timedelta(days=6)
        return ini, agora, ini - timedelta(days=7), agora - timedelta(days=7), 'vs. 7 dias anteriores'
    if periodo == 'mes':
        ini = hoje.replace(day=1)
        ant_fim = ini - timedelta(seconds=1)
        ant_ini = ant_fim.replace(day=1, hour=0, minute=0, second=0)
        dias = (agora - ini)
        return ini, agora, ant_ini, ant_ini + dias, 'vs. mesmo período do mês passado'
    nome_dia = DIAS[agora.weekday()].lower()
    artigo = 'passado' if agora.weekday() in (5, 6) else 'passada'
    return hoje, agora, hoje - timedelta(days=7), agora - timedelta(days=7), f'vs. {nome_dia} {artigo}'


def _vendas(tid, ini, fim):
    return Sale.query.filter(Sale.tenant_id == tid, Sale.status == 'confirmed',
                             Sale.created_at >= ini, Sale.created_at <= fim)


def dados(tenant, periodo='hoje'):
    tid = tenant.id
    agora = datetime.now()
    if periodo not in ('hoje', '7d', 'mes'):
        periodo = 'hoje'
    ini, fim, ant_ini, ant_fim, comp_txt = _janela(periodo, agora)

    q = _vendas(tid, ini, fim)
    fat, pedidos = q.with_entities(func.coalesce(func.sum(Sale.total), 0.0), func.count(Sale.id)).first()
    fat, pedidos = float(fat or 0), int(pedidos or 0)
    entrega = q.filter(Sale.delivery_mode == 'entrega').count()
    fat_ant = float(_vendas(tid, ant_ini, ant_fim).with_entities(func.coalesce(func.sum(Sale.total), 0.0)).scalar() or 0)
    variacao = None if fat_ant <= 0 else round((fat - fat_ant) / fat_ant * 100)

    mes_ini = datetime.combine(agora.date().replace(day=1), datetime.min.time())
    tk_mes = float(_vendas(tid, mes_ini, agora).with_entities(func.avg(Sale.total)).scalar() or 0)

    # Lucro estimado = (subtotal − desconto) − custo dos itens vendidos
    receita = float(q.with_entities(func.coalesce(func.sum(Sale.subtotal - func.coalesce(Sale.discount, 0)), 0.0)).scalar() or 0)
    custo = float(db.session.query(func.coalesce(func.sum(SaleItem.cost_price * SaleItem.quantity), 0.0))
                  .join(Sale, SaleItem.sale_id == Sale.id)
                  .filter(Sale.tenant_id == tid, Sale.status == 'confirmed',
                          Sale.created_at >= ini, Sale.created_at <= fim).scalar() or 0)
    lucro = receita - custo

    # Vendas por hora (hoje) ou por dia (7 dias / mês)
    serie, por_hora = [], periodo == 'hoje'
    linhas = q.with_entities(Sale.created_at, Sale.total).all()
    if por_hora:
        acc = {}
        for c, t in linhas:
            acc[c.hour] = acc.get(c.hour, 0) + (t or 0)
        if acc:
            for h in range(min(acc), max(acc) + 1):
                serie.append((f'{h:02d}h', acc.get(h, 0)))
    else:
        acc = {}
        for c, t in linhas:
            acc[c.date()] = acc.get(c.date(), 0) + (t or 0)
        d = ini.date()
        while d <= fim.date():
            serie.append((d.strftime('%d/%m'), acc.get(d, 0)))
            d += timedelta(days=1)
    pico_v = max((v for _, v in serie), default=0)
    barras = [{'label': l, 'valor': brl(v).replace(',00', ''), 'alt': f'{max(2, round(v / pico_v * 82)) if pico_v else 2}%',
               'pico': v == pico_v and v > 0} for l, v in serie]
    com_venda = [(l, v) for l, v in serie if v > 0]
    pico = max(com_venda, key=lambda x: x[1]) if com_venda else None
    calmo = min(com_venda, key=lambda x: x[1]) if len(com_venda) > 1 else None

    # Formas de pagamento (pagamento combinado é dividido entre as formas usadas)
    soma = {}
    for metodo, total, entradas in q.with_entities(Sale.payment_method, Sale.total, Sale.payment_entries).all():
        if metodo == 'combinado' and entradas:
            try:
                for e in json.loads(entradas):
                    g = GRUPOS_PGTO.get(e.get('method'), 'Outros')
                    soma[g] = soma.get(g, 0) + float(e.get('amount') or 0)
                continue
            except Exception:
                pass
        g = GRUPOS_PGTO.get(metodo, 'Outros')
        soma[g] = soma.get(g, 0) + (total or 0)
    tot_pg = sum(soma.values()) or 1
    pagamentos = [{'nome': k, 'pct': round(v / tot_pg * 100), 'valor': brl(v), 'cor': CORES_PGTO.get(k, '#e3e5ea')}
                  for k, v in sorted(soma.items(), key=lambda x: -x[1]) if v > 0]

    # Precisa de atenção
    atencao = []
    pend = PedidoOnline.query.filter_by(tenant_id=tid, status='pending').count()
    if pend:
        atencao.append({'n': pend, 'txt': 'pedido online aguardando aceite' if pend == 1 else 'pedidos online aguardando aceite', 'acao': 'Abrir',
                        'url': '/pedidos-online/', 'tom': 'aviso'})
    if not tenant.is_lanchonete:
        combo_ids = db.session.query(ComboItem.combo_id).distinct()
        esg = (Product.query.filter(Product.tenant_id == tid, Product.active == True,
                                    Product.pack_parent_id == None, Product.stock_quantity <= 0)
               .filter(~Product.id.in_(combo_ids)).order_by(Product.name).with_entities(Product.name).all())
        if esg:
            nomes = ', '.join(n for (n,) in esg[:2]) + (f' e mais {len(esg) - 2}' if len(esg) > 2 else '')
            atencao.append({'n': len(esg), 'txt': (f'produto esgotado ({nomes})' if len(esg) == 1 else f'produtos esgotados ({nomes})'), 'acao': 'Repor',
                            'url': '/estoque/', 'tom': 'perigo'})
    atrasadas = Sale.query.filter(Sale.tenant_id == tid, Sale.status == 'confirmed', Sale.delivery_mode == 'entrega',
                                  Sale.dispatched_at != None, Sale.delivered_at == None,
                                  Sale.dispatched_at < agora - timedelta(minutes=40)).count()
    if atrasadas:
        atencao.append({'n': atrasadas, 'txt': 'entrega em rota há mais de 40 min' if atrasadas == 1 else 'entregas em rota há mais de 40 min', 'acao': 'Ver',
                        'url': '/entregas/', 'tom': 'neutro'})

    # Mais vendidos no período
    top = (db.session.query(SaleItem.product_name, func.sum(SaleItem.quantity))
           .join(Sale, SaleItem.sale_id == Sale.id)
           .filter(Sale.tenant_id == tid, Sale.status == 'confirmed', Sale.created_at >= ini, Sale.created_at <= fim)
           .group_by(SaleItem.product_name).order_by(func.sum(SaleItem.quantity).desc()).limit(5).all())
    mx = float(top[0][1]) if top else 1
    mais = [{'nome': n, 'qtd': int(q_) if float(q_).is_integer() else round(float(q_), 2),
             'w': f'{round(float(q_) / mx * 100)}%'} for n, q_ in top]

    titulo = {'hoje': 'Resumo de hoje', '7d': 'Resumo dos últimos 7 dias', 'mes': 'Resumo do mês'}[periodo]
    rotulo = {'hoje': 'hoje', '7d': 'nos 7 dias', 'mes': 'no mês'}[periodo]
    return {
        'periodo': periodo, 'titulo': titulo, 'rotulo': rotulo,
        'data_txt': f'{DIAS[agora.weekday()]}, {agora.day} de {MESES[agora.month - 1]}',
        'faturamento': brl(fat), 'variacao': variacao, 'comp_txt': comp_txt,
        'pedidos': pedidos, 'balcao': pedidos - entrega, 'entrega': entrega,
        'ticket': brl(fat / pedidos) if pedidos else brl(0), 'ticket_mes': brl(tk_mes),
        'lucro': brl(lucro), 'margem': (f'{lucro / receita * 100:.1f}%'.replace('.', ',') if receita > 0 else '—'),
        'por_hora': por_hora, 'barras': barras,
        'pico': (pico[0], brl(pico[1])) if pico else None, 'calmo': calmo[0] if calmo else None,
        'pagamentos': pagamentos, 'atencao': atencao, 'mais': mais,
    }
