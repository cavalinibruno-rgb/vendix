from app import db
from app.models.user import User
import os


def seed_categorias_nativas(tenant_id):
    """Garante as categorias nativas (Combos, Promoção) da loja — protegidas,
    não apagáveis. Se a loja já tiver uma equivalente, apenas a marca protegida."""
    from app.models.product import ProductType
    existentes = ProductType.query.filter_by(tenant_id=tenant_id).all()
    maxnum = max([t.type_number or 0 for t in existentes], default=0)
    for nome, aliases in [('Combos', ('combos', 'combo')),
                          ('Promoção', ('promoção', 'promocao'))]:
        ja = [t for t in existentes if (t.name or '').lower() in aliases]
        if ja:
            for t in ja:
                t.protected = True
        else:
            maxnum += 1
            db.session.add(ProductType(tenant_id=tenant_id, name=nome,
                                       protected=True, type_number=maxnum))


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
