from app import db
from datetime import datetime

class Motoboy(db.Model):
    __tablename__ = 'motoboys'

    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    name       = db.Column(db.String(128), nullable=False)
    phone      = db.Column(db.String(32))
    active     = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
