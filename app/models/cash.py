from app import db
from datetime import datetime

class CashRegister(db.Model):
    __tablename__ = 'cash_registers'

    id             = db.Column(db.Integer, primary_key=True)
    tenant_id      = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    opened_by      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    closed_by      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    opening_amount = db.Column(db.Float, default=0)   # troco inicial
    closing_amount = db.Column(db.Float, nullable=True)  # valor contado no fechamento
    status         = db.Column(db.String(16), default='open')  # open | closed
    operator_employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    operator_name  = db.Column(db.String(128), nullable=True)
    notes          = db.Column(db.Text)
    closing_data   = db.Column(db.Text)
    opened_at      = db.Column(db.DateTime, default=datetime.now)
    closed_at      = db.Column(db.DateTime, nullable=True)

    opener   = db.relationship('User', foreign_keys=[opened_by], backref='opened_registers')
    closer   = db.relationship('User', foreign_keys=[closed_by], backref='closed_registers')
    operator = db.relationship('Employee', foreign_keys=[operator_employee_id])
