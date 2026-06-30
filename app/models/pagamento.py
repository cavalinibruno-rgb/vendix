from app import db
from datetime import datetime

class Pagamento(db.Model):
    __tablename__ = 'pagamentos'

    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    valor       = db.Column(db.Numeric(10, 2), nullable=False)
    plano       = db.Column(db.String(16), nullable=False)  # mensal | anual
    paid_at     = db.Column(db.DateTime, nullable=False, default=datetime.now)
    observacao    = db.Column(db.Text, nullable=True)
    mp_payment_id = db.Column(db.String(64), nullable=True, unique=True)
    created_at    = db.Column(db.DateTime, default=datetime.now)

    tenant = db.relationship('Tenant', backref=db.backref('pagamentos', lazy=True))
