from app import db
from datetime import datetime
import json as _json
import secrets


class PedidoOnline(db.Model):
    __tablename__ = 'pedidos_online'

    id             = db.Column(db.Integer, primary_key=True)
    token          = db.Column(db.String(48), unique=True, nullable=True)
    tenant_id      = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    sale_id        = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    # Cliente (sem cadastro)
    cliente_nome   = db.Column(db.String(128), nullable=False)
    cliente_tel    = db.Column(db.String(32))
    # Entrega
    bairro_id      = db.Column(db.Integer, db.ForeignKey('neighborhoods.id'), nullable=True)
    bairro_nome    = db.Column(db.String(64))
    endereco       = db.Column(db.String(256))
    rua            = db.Column(db.String(128))
    numero         = db.Column(db.String(16))
    complemento    = db.Column(db.String(64))
    taxa_entrega   = db.Column(db.Float, default=0)
    # Pagamento
    payment_method = db.Column(db.String(32))  # entrega_dinheiro | entrega_cartao | entrega_pix
    troco_para     = db.Column(db.Float, nullable=True)
    # Itens (snapshot JSON)
    items_json     = db.Column(db.Text)
    subtotal       = db.Column(db.Float, default=0)
    total          = db.Column(db.Float, default=0)
    notes          = db.Column(db.Text)
    # Status: pending | accepted | rejected | dispatched
    status         = db.Column(db.String(16), default='pending')
    accepted_at    = db.Column(db.DateTime, nullable=True)
    rejected_at    = db.Column(db.DateTime, nullable=True)
    reject_reason  = db.Column(db.String(256), nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.now)

    tenant = db.relationship('Tenant', foreign_keys=[tenant_id])

    @property
    def items(self):
        try:
            return _json.loads(self.items_json or '[]')
        except Exception:
            return []
