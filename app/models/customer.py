from app import db
from datetime import datetime

class Neighborhood(db.Model):
    __tablename__ = 'neighborhoods'

    id           = db.Column(db.Integer, primary_key=True)
    tenant_id    = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    name         = db.Column(db.String(64), nullable=False)
    delivery_fee = db.Column(db.Float, default=0)
    created_at   = db.Column(db.DateTime, default=datetime.now)

    customers = db.relationship('Customer', back_populates='neighborhood', lazy=True)

class Customer(db.Model):
    __tablename__ = 'customers'

    id              = db.Column(db.Integer, primary_key=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    neighborhood_id = db.Column(db.Integer, db.ForeignKey('neighborhoods.id'), nullable=True)
    name            = db.Column(db.String(128), nullable=False)
    phone           = db.Column(db.String(32))
    cep             = db.Column(db.String(9))
    bairro          = db.Column(db.String(64))   # nome do bairro em texto (preenchido pelo CEP)
    address         = db.Column(db.String(256))
    address_number  = db.Column(db.String(16))
    address_ref     = db.Column(db.String(256))
    delivery_fee    = db.Column(db.Float, default=0)
    notes           = db.Column(db.Text)
    created_at      = db.Column(db.DateTime, default=datetime.now)

    neighborhood = db.relationship('Neighborhood', back_populates='customers')
