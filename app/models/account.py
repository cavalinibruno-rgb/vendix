from app import db
from datetime import datetime

class AccountPayment(db.Model):
    __tablename__ = 'account_payments'

    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    amount      = db.Column(db.Float, nullable=False)
    notes       = db.Column(db.Text)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    created_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    customer = db.relationship('Customer', backref='payments', lazy=True)
