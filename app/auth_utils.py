"""Utilitário de autenticação de operadores para ações sensíveis."""
from app.models.vale import Employee
from app.models.user import User


def autenticar_operador(tenant_id, username, password):
    """
    Valida credenciais para ações que requerem autorização (caixa, estoque, cancelamento).
    Verifica primeiro os operadores (Employee), depois o lojista (User).
    Retorna (nome_responsavel, True) ou (None, False).
    """
    if not username or not password:
        return None, False

    # Operador de caixa / funcionário
    emp = Employee.query.filter_by(tenant_id=tenant_id, username=username).first()
    if emp and emp.check_password(password):
        return emp.name, True

    # Lojista
    user = User.query.filter_by(tenant_id=tenant_id, username=username).first()
    if user and user.check_password(password):
        return user.display_name or user.username, True

    return None, False
