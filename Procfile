web: python migrate.py && VENDIX_SKIP_BOOT_MIGRATIONS=1 gunicorn run:app --workers=2 --threads=4 --worker-class=gthread --timeout=120 --keep-alive=5
