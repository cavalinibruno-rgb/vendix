from app import db
from datetime import datetime, timedelta
import secrets

class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_tokens'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token      = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used       = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship('User', backref='reset_tokens')

    @staticmethod
    def criar(user_id):
        # Invalida tokens anteriores do mesmo usuário
        PasswordResetToken.query.filter_by(user_id=user_id, used=False).update({'used': True})
        token = secrets.token_urlsafe(48)
        rt = PasswordResetToken(
            user_id    = user_id,
            token      = token,
            expires_at = datetime.now() + timedelta(hours=1),
        )
        db.session.add(rt)
        return rt

    @property
    def valido(self):
        return not self.used and datetime.now() < self.expires_at
