from app import db
from datetime import datetime

class CashWithdrawal(db.Model):
    __tablename__ = 'cash_withdrawals'

    id               = db.Column(db.Integer, primary_key=True)
    tenant_id        = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    cash_register_id = db.Column(db.Integer, db.ForeignKey('cash_registers.id'), nullable=False)
    amount           = db.Column(db.Float, nullable=False)
    motivo           = db.Column(db.String(256), nullable=False)
    operator_name    = db.Column(db.String(128), nullable=False)
    created_at       = db.Column(db.DateTime, default=datetime.now)
