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
    settings      = db.Column(db.Text, default='{}')  # JSON de configurações
    logo_url         = db.Column(db.String(512), nullable=True)
    logo_data        = db.Column(db.LargeBinary, nullable=True)
    logo_mime        = db.Column(db.String(32), nullable=True)
    preapproval_id         = db.Column(db.String(128), nullable=True)
    payment_id             = db.Column(db.String(128), nullable=True)
    subscription_cancelled = db.Column(db.Boolean, default=False, nullable=False)
    profile_complete = db.Column(db.Boolean, default=True, nullable=False)
    street           = db.Column(db.String(256), nullable=True)
    number           = db.Column(db.String(16), nullable=True)
    neighborhood     = db.Column(db.String(128), nullable=True)
    city             = db.Column(db.String(128), nullable=True)
    state            = db.Column(db.String(2), nullable=True)
    cep              = db.Column(db.String(9), nullable=True)
    event_mode       = db.Column(db.Boolean, default=False, nullable=False)
    business_type    = db.Column(db.String(16), default='varejo', nullable=False)  # varejo | lanchonete
    created_at    = db.Column(db.DateTime, default=datetime.now)

    users = db.relationship('User', backref='tenant', lazy=True)

    @property
    def is_lanchonete(self):
        return self.business_type == 'lanchonete'

    @property
    def is_active(self):
        if self.status != 'active':
            return False
        if self.expires_at and self.expires_at < datetime.now():
            return False
        return True

    def get_settings(self):
        import json
        try:
            return json.loads(self.settings or '{}')
        except Exception:
            return {}

    def save_settings(self, data):
        import json
        self.settings = json.dumps(data)

    def __repr__(self):
        return f'<Tenant {self.slug}>'
