"""Prepara o banco de dados — roda UMA vez por deploy, antes do gunicorn.

Chamado pelo Procfile: `python migrate.py && gunicorn ...`
Se este script falhar (banco fora do ar, migração com erro), o gunicorn
NEM SOBE e o Railway mantém o container antigo servindo — o app nunca
roda com o banco desatualizado.
"""
import os
import sys

# Garante que a preparação roda mesmo se a env do Procfile vazar pro processo
os.environ.pop('VENDIX_SKIP_BOOT_MIGRATIONS', None)

from app import create_app  # noqa: E402  (create_app com o padrão = prepara o banco)

try:
    create_app()
    print('[migrate] Banco preparado com sucesso (tabelas + migracoes + seed).')
except Exception as e:  # noqa: BLE001
    print(f'[migrate] FALHOU: {e}', file=sys.stderr)
    sys.exit(1)
