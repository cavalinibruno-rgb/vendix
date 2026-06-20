from app import db
from datetime import datetime

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

    product = db.relationship('Product', backref='movements', lazy=True)
