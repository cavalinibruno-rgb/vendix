from app import create_app, db
from app.models.user import User

app = create_app()
with app.app_context():
    db.create_all()
    existing = User.query.filter_by(email='bcavalini@hotmail.com').first()
    if existing:
        print('Usuário master já existe.')
    else:
        master = User(
            tenant_id=None,
            username='master',
            email='bcavalini@hotmail.com',
            display_name='Bruno Cavalini',
            role='master'
        )
        master.set_password('45127579190325131528')
        db.session.add(master)
        db.session.commit()
        print('Usuário master criado com sucesso!')
