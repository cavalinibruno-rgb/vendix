from app import db
from datetime import datetime

class Tenant(db.Model):
    __tablename__ = 'tenants'

    id            = db.Column(db.Integer, primary_key=True)
    slug          = db.Column(db.String(64), unique=True, nullable=False)  # ex: padaria-do-joao
    store_name    = db.Column(db.String(128), nullable=False)
    email         = db.Column(db.String(128), unique=True, nullable=False)
    phone         = db.Column(db.String(32))
    plan          = db.Column(db.String(32), default='mensal')
    status        = db.Column(db.String(16), default='active')  # active | suspended | cancelled
    expires_at    = db.Column(db.DateTime, nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship('User', backref='tenant', lazy=True)

    @property
    def is_active(self):
        if self.status != 'active':
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        return True

    def __repr__(self):
        return f'<Tenant {self.slug}>'
