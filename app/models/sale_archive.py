from app import db
from datetime import datetime

class SaleArchive(db.Model):
    __tablename__ = 'sales_archive'

    id               = db.Column(db.Integer, primary_key=True)
    original_id      = db.Column(db.Integer, nullable=False, index=True)
    tenant_id        = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    sale_number      = db.Column(db.Integer, nullable=True)
    customer_id      = db.Column(db.Integer, nullable=True)
    delivery_mode    = db.Column(db.String(16))
    delivery_fee     = db.Column(db.Float, default=0)
    subtotal         = db.Column(db.Float, default=0)
    total            = db.Column(db.Float, default=0)
    payment_method   = db.Column(db.String(32))
    notes            = db.Column(db.Text)
    status           = db.Column(db.String(16))
    source           = db.Column(db.String(16))
    app_name         = db.Column(db.String(64))
    amount_paid      = db.Column(db.Float, nullable=True)
    discount         = db.Column(db.Float, default=0)
    discount_type    = db.Column(db.String(8), nullable=True)
    cashier_name     = db.Column(db.String(128), nullable=True)
    cancelled_at     = db.Column(db.DateTime, nullable=True)
    cancelled_by_name= db.Column(db.String(64), nullable=True)
    cancel_reason    = db.Column(db.Text, nullable=True)
    employee_id      = db.Column(db.Integer, nullable=True)
    created_at       = db.Column(db.DateTime, nullable=False, index=True)
    archived_at      = db.Column(db.DateTime, default=datetime.now)

    # Itens serializados em JSON (desnormalizado para economizar espaço)
    items_json       = db.Column(db.Text, nullable=True)
