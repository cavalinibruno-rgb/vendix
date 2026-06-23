from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id           = db.Column(db.Integer, primary_key=True)
    tenant_id    = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True)  # null = master
    username     = db.Column(db.String(64), nullable=False)
    email        = db.Column(db.String(128), unique=True, nullable=False)
    password_hash= db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(128))
    role         = db.Column(db.String(16), default='operator')  # master | admin | operator
    created_at   = db.Column(db.DateTime, default=datetime.now)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_master(self):
        return self.role == 'master'

    @property
    def is_employee(self):
        return False

    def __repr__(self):
        return f'<User {self.username}>'

@login_manager.user_loader
def load_user(user_id):
    # Suporte a Employee login: prefixo "e_<id>" vs User: "<id>"
    if str(user_id).startswith('e_'):
        from app.models.vale import Employee
        emp = Employee.query.get(int(user_id[2:]))
        if emp:
            return EmployeeLoginProxy(emp)
        return None
    return User.query.get(int(user_id))


class EmployeeLoginProxy:
    """Adapta Employee para funcionar com Flask-Login."""
    def __init__(self, emp):
        self._emp = emp
        self.id           = f'e_{emp.id}'
        self.tenant_id    = emp.tenant_id
        self.username     = emp.username
        self.email        = None
        self.display_name = emp.name
        self.role         = emp.role  # 'caixa'
        self.is_active    = True
        self.is_anonymous = False
        self.is_authenticated = True

    @property
    def is_master(self):
        return False

    @property
    def is_employee(self):
        return True

    def get_id(self):
        return self.id

    def check_password(self, pwd):
        return self._emp.check_password(pwd)
