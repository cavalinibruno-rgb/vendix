from app import db
from datetime import datetime

class Sale(db.Model):
    __tablename__ = 'sales'

    id              = db.Column(db.Integer, primary_key=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    customer_id     = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)
    delivery_mode   = db.Column(db.String(16), default='retirada')  # retirada | entrega
    delivery_fee    = db.Column(db.Float, default=0)
    subtotal        = db.Column(db.Float, default=0)
    total           = db.Column(db.Float, default=0)
    payment_method  = db.Column(db.String(16), nullable=False)  # dinheiro | cartao | pix | conta
    notes           = db.Column(db.Text)
    status          = db.Column(db.String(16), default='confirmed')  # confirmed | cancelled
    source          = db.Column(db.String(16), default='loja')       # loja | app
    app_name        = db.Column(db.String(64))                        # iFood, Anotaí, etc.
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    items    = db.relationship('SaleItem', backref='sale', lazy=True, cascade='all, delete-orphan')
    customer = db.relationship('Customer', backref='sales', lazy=True)

class SaleItem(db.Model):
    __tablename__ = 'sale_items'

    id          = db.Column(db.Integer, primary_key=True)
    sale_id     = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id  = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_name= db.Column(db.String(128), nullable=False)  # salvo no momento da venda
    unit_price  = db.Column(db.Float, nullable=False)
    quantity    = db.Column(db.Float, nullable=False, default=1)
    total       = db.Column(db.Float, nullable=False)
