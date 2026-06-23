from app import db
from datetime import datetime

class Coupon(db.Model):
    __tablename__ = 'coupons'

    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    code        = db.Column(db.String(32), nullable=False)
    coupon_type = db.Column('type', db.String(8), nullable=False)   # 'percent' | 'value'
    amount      = db.Column(db.Float, nullable=False)
    active      = db.Column(db.Boolean, default=True)
    starts_at   = db.Column(db.DateTime, nullable=True)
    ends_at     = db.Column(db.DateTime, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.now)
