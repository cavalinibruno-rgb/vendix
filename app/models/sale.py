from app import db
from datetime import datetime

class Sale(db.Model):
    __tablename__ = 'sales'

    id              = db.Column(db.Integer, primary_key=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    customer_id     = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)
    delivery_mode   = db.Column(db.String(16), default='retirada')  # retirada | entrega
    delivery_fee    = db.Column(db.Float, default=0)
    delivery_address = db.Column(db.String(256), nullable=True)
    subtotal        = db.Column(db.Float, default=0)
    total           = db.Column(db.Float, default=0)
    payment_method  = db.Column(db.String(32), nullable=False)  # dinheiro | cartao | pix | conta
    notes           = db.Column(db.Text)
    status          = db.Column(db.String(16), default='confirmed')  # confirmed | cancelled
    source          = db.Column(db.String(16), default='loja')       # loja | app
    app_name        = db.Column(db.String(64))                        # iFood, Anotaí, etc.
    amount_paid      = db.Column(db.Float, nullable=True)
    change_amount    = db.Column(db.Float, nullable=True)
    discount         = db.Column(db.Float, nullable=True, default=0)
    discount_type    = db.Column(db.String(8), nullable=True)  # 'value' | 'percent'
    dispatched_at     = db.Column(db.DateTime, nullable=True)
    motoboy_id        = db.Column(db.Integer, db.ForeignKey('motoboys.id'), nullable=True)
    motoboy_name      = db.Column(db.String(128), nullable=True)
    cancelled_at      = db.Column(db.DateTime, nullable=True)
    cancelled_by_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancelled_by_name = db.Column(db.String(64), nullable=True)
    cancel_reason     = db.Column(db.Text, nullable=True)
    cashier_name      = db.Column(db.String(128), nullable=True)
    delivered_at      = db.Column(db.DateTime, nullable=True)
    payment_entries   = db.Column(db.Text, nullable=True)  # JSON para pagamento combinado
    employee_id       = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    sale_number       = db.Column(db.Integer, nullable=True)  # sequencial por tenant
    cash_register_id  = db.Column(db.Integer, db.ForeignKey('cash_registers.id'), nullable=True)
    created_at       = db.Column(db.DateTime, default=datetime.now)

    items    = db.relationship('SaleItem', backref='sale', lazy=True, cascade='all, delete-orphan')
    customer = db.relationship('Customer', backref='sales', lazy=True)
    employee = db.relationship('Employee', backref='sales', lazy=True, foreign_keys=[employee_id])

    PGTO_LABELS = {
        'dinheiro': 'Dinheiro', 'cartao': 'Cartão', 'cartao_credito': 'Crédito',
        'cartao_debito': 'Débito', 'pix': 'Pix', 'conta': 'Conta',
        'funcionario': 'Funcionário',
        'entrega_dinheiro': 'Dinheiro', 'entrega_pix': 'Pix', 'entrega_cartao': 'Cartão',
        'entrega_cartao_credito': 'Crédito', 'entrega_cartao_debito': 'Débito',
        'combinado': 'Combinado',
    }

    @property
    def payment_entries_list(self):
        """Lista [{method, amount}] do pagamento combinado (ou vazia)."""
        import json
        if self.payment_method == 'combinado' and self.payment_entries:
            try:
                return json.loads(self.payment_entries)
            except Exception:
                return []
        return []

    @property
    def payment_label(self):
        """Rótulo legível da forma de pagamento (Combinado permanece 'Combinado')."""
        return self.PGTO_LABELS.get(self.payment_method, self.payment_method)

class SaleItem(db.Model):
    __tablename__ = 'sale_items'

    id          = db.Column(db.Integer, primary_key=True)
    sale_id     = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id  = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_name= db.Column(db.String(128), nullable=False)  # salvo no momento da venda
    unit_price  = db.Column(db.Float, nullable=False)
    cost_price  = db.Column(db.Float, nullable=True, default=0)  # custo no momento da venda
    quantity    = db.Column(db.Float, nullable=False, default=1)
    total       = db.Column(db.Float, nullable=False)
