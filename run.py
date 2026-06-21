import traceback as _tb

_startup_error = None
try:
    from app import create_app
    app = create_app()
except Exception:
    _startup_error = _tb.format_exc()
    from flask import Flask as _Flask
    app = _Flask(__name__)

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def _show_error(path):
        return f'<pre style="padding:20px;font-size:13px">STARTUP ERROR:\n\n{_startup_error}</pre>', 500

if __name__ == '__main__':
    app.run(debug=False)
