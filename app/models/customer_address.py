from app import db
from datetime import datetime

class CustomerAddress(db.Model):
    __tablename__ = 'customer_addresses'

    id              = db.Column(db.Integer, primary_key=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    customer_id     = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    label           = db.Column(db.String(64))
    address         = db.Column(db.String(256))
    neighborhood_id = db.Column(db.Integer, db.ForeignKey('neighborhoods.id'), nullable=True)
    delivery_fee    = db.Column(db.Float, default=0)
    created_at      = db.Column(db.DateTime, default=datetime.now)
