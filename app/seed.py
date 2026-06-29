from app import db
from app.models.user import User
import os

def seed_master():
    email    = os.environ.get('MASTER_EMAIL')
    password = os.environ.get('MASTER_PASSWORD')
    if not email or not password:
        return  # Não cria conta master sem variáveis de ambiente definidas
    if not User.query.filter_by(email=email).first():
        master = User(
            tenant_id=None,
            username='master',
            email=email,
            display_name='Master',
            role='master'
        )
        master.set_password(password)
        db.session.add(master)
        db.session.commit()
