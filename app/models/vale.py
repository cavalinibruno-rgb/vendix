from app import db
from datetime import datetime

class Employee(db.Model):
    __tablename__ = 'employees'
    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    name       = db.Column(db.String(128), nullable=False)
    role       = db.Column(db.String(32), default='caixa')  # caixa | motoboy
    created_at = db.Column(db.DateTime, default=datetime.now)
    vales      = db.relationship('Vale', backref='employee', lazy=True, cascade='all, delete-orphan')

class Vale(db.Model):
    __tablename__ = 'vales'
    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    amount      = db.Column(db.Float, nullable=False)
    date        = db.Column(db.Date, nullable=False, default=datetime.now().date)
    notes       = db.Column(db.Text)
    created_at  = db.Column(db.DateTime, default=datetime.now)
