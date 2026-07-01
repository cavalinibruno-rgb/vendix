from app import db
from datetime import datetime, timedelta
import random, string

class MasterOTP(db.Model):
    __tablename__ = 'master_otp'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    code       = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used       = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    @staticmethod
    def gerar(user_id):
        # Invalida códigos anteriores do mesmo usuário
        MasterOTP.query.filter_by(user_id=user_id, used=False).update({'used': True})
        code = ''.join(random.choices(string.digits, k=6))
        otp  = MasterOTP(
            user_id    = user_id,
            code       = code,
            expires_at = datetime.now() + timedelta(minutes=10),
        )
        db.session.add(otp)
        return otp

    @property
    def valido(self):
        return not self.used and self.expires_at > datetime.now()
