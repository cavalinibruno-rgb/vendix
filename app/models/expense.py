from app import db
from datetime import datetime

CATEGORIAS = [
    'Aluguel',
    'Água / Luz / Gás',
    'Internet / Telefone',
    'Salários',
    'Fornecedores',
    'Marketing',
    'Manutenção',
    'Impostos / Taxas',
    'Embalagens',
    'Transporte',
    'Outros',
]

class Expense(db.Model):
    __tablename__ = 'expenses'

    id               = db.Column(db.Integer, primary_key=True)
    tenant_id        = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    cash_register_id = db.Column(db.Integer, db.ForeignKey('cash_registers.id'), nullable=True)
    date             = db.Column(db.Date, nullable=False, default=datetime.today)
    category         = db.Column(db.String(64), nullable=False)
    description      = db.Column(db.String(256), nullable=True)
    amount           = db.Column(db.Float, nullable=False)
    payment_method   = db.Column(db.String(16), default='dinheiro')
    operator_name    = db.Column(db.String(128), nullable=True)
    created_at       = db.Column(db.DateTime, default=datetime.now)
