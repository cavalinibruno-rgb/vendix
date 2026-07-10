from app import db
from datetime import datetime

class AccountPayment(db.Model):
    __tablename__ = 'account_payments'

    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    amount      = db.Column(db.Float, nullable=False)
    notes       = db.Column(db.Text)
    created_at  = db.Column(db.DateTime, default=datetime.now)
    created_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by_name = db.Column(db.String(128))

    customer = db.relationship('Customer', backref='payments', lazy=True)
