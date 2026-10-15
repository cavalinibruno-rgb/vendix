from app import db
from datetime import datetime
from sqlalchemy import event

class StockMovement(db.Model):
    __tablename__ = 'stock_movements'

    id           = db.Column(db.Integer, primary_key=True)
    tenant_id    = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    product_id   = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_name = db.Column(db.String(128), nullable=False)
    type         = db.Column(db.String(8), nullable=False)   # entrada | saida
    quantity     = db.Column(db.Integer, nullable=False)
    motive       = db.Column(db.String(128))
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    user_name    = db.Column(db.String(64))
    created_at   = db.Column(db.DateTime, default=datetime.now)
    estoque_apos = db.Column(db.Integer, nullable=True)  # estoque do produto logo após esta movimentação

    product = db.relationship('Product', backref='movements', lazy=True)


@event.listens_for(StockMovement, 'init')
def _anota_estoque_apos(target, args, kwargs):
    """Anota o estoque do produto no momento em que a movimentação é criada.

    Em todo o sistema o estoque é alterado ANTES de criar a movimentação, então o
    valor lido aqui já é o "depois" — como um extrato. Lê do mapa de identidade da
    sessão (sem forçar flush), pegando a alteração ainda não gravada.
    """
    pid = kwargs.get('product_id')
    if kwargs.get('estoque_apos') is not None or not pid:
        return
    from app.models.product import Product
    with db.session.no_autoflush:
        prod = db.session.get(Product, pid)
    if prod is not None:
        target.estoque_apos = prod.stock_quantity
