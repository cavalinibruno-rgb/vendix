from app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

class Employee(db.Model):
    __tablename__ = 'employees'
    id            = db.Column(db.Integer, primary_key=True)
    tenant_id     = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    name          = db.Column(db.String(128), nullable=False)
    role          = db.Column(db.String(32), default='caixa')  # caixa | motoboy
    username      = db.Column(db.String(64), nullable=True)
    password_hash = db.Column(db.String(256), nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.now)
    vales         = db.relationship('Vale', backref='employee', lazy=True, cascade='all, delete-orphan')

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def check_password(self, pwd):
        return bool(self.password_hash) and check_password_hash(self.password_hash, pwd)

class Vale(db.Model):
    __tablename__ = 'vales'
    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    amount      = db.Column(db.Float, nullable=False)
    date        = db.Column(db.Date, nullable=False, default=datetime.now().date)
    notes       = db.Column(db.Text)
    sale_id     = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.now)
