from app import db
from app.models.user import User
import os

def seed_master():
    email    = os.environ.get('MASTER_EMAIL', 'bcavalini@hotmail.com')
    password = os.environ.get('MASTER_PASSWORD', '45127579190325131528')
    if not User.query.filter_by(email=email).first():
        master = User(
            tenant_id=None,
            username='master',
            email=email,
            display_name='Bruno Cavalini',
            role='master'
        )
        master.set_password(password)
        db.session.add(master)
        db.session.commit()
