from app import db
from datetime import datetime

class PendingRegistration(db.Model):
    __tablename__ = 'pending_registrations'

    id            = db.Column(db.Integer, primary_key=True)
    store_name    = db.Column(db.String(128), nullable=False)
    email         = db.Column(db.String(128), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    plano         = db.Column(db.String(16), nullable=False)  # mensal | anual
    preference_id = db.Column(db.String(128))
    payment_id    = db.Column(db.String(128))
    status        = db.Column(db.String(16), default='pending')  # pending | created | failed
    created_at    = db.Column(db.DateTime, default=datetime.now)
