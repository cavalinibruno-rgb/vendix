from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, abort
from flask_login import login_required, current_user
from app import db
from app import r2
from app.models.app_release import AppRelease
from functools import wraps
import hashlib, base64, datetime

download_bp = Blueprint('download', __name__)

MAX_SIZE = 150 * 1024 * 1024  # 150 MB


def master_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_master:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _sha512_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha512(data).digest()).decode()


@download_bp.route('/download')
def pagina():
    releases = AppRelease.query.order_by(AppRelease.uploaded_at.desc()).all()
    latest   = releases[0] if releases else None
    return render_template('download.html', latest=latest, releases=releases)


@download_bp.route('/download/<int:release_id>/arquivo')
def arquivo(release_id):
    release = AppRelease.query.get_or_404(release_id)
    if release.file_url:
        return redirect(release.file_url)
    mime = 'application/vnd.android.package-archive' if release.platform == 'android' else 'application/octet-stream'
    return Response(
        release.file_data,
        mimetype=mime,
        headers={'Content-Disposition': f'attachment; filename="{release.filename}"'}
    )


# Rota usada pelo electron-updater para baixar o .exe pelo nome do arquivo
@download_bp.route('/download/updates/<filename>')
def update_file(filename):
    release = AppRelease.query.filter_by(filename=filename, platform='windows').order_by(AppRelease.uploaded_at.desc()).first_or_404()
    if release.file_url:
        return redirect(release.file_url)
    return Response(
        release.file_data,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{release.filename}"'}
    )


# Manifesto lido pelo electron-updater para verificar se há nova versão
@download_bp.route('/download/updates/latest.yml')
def latest_yml():
    release = AppRelease.query.filter_by(platform='windows').order_by(AppRelease.uploaded_at.desc()).first()
    if not release:
        abort(404)
    if release.file_sha512:
        sha = release.file_sha512
    elif release.file_data:
        sha = _sha512_b64(release.file_data)
    else:
        abort(503)
    date = release.uploaded_at.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    yml = (
        f"version: {release.version}\n"
        f"files:\n"
        f"  - url: {release.filename}\n"
        f"    sha512: {sha}\n"
        f"    size: {release.file_size}\n"
        f"path: {release.filename}\n"
        f"sha512: {sha}\n"
        f"releaseDate: '{date}'\n"
    )
    return Response(yml, mimetype='text/yaml')


@download_bp.route('/master/app/upload', methods=['GET', 'POST'])
@login_required
@master_required
def upload():
    if request.method == 'POST':
        version     = request.form.get('version', '').strip()
        description = request.form.get('description', '').strip()
        platform    = request.form.get('platform', 'windows')
        f           = request.files.get('arquivo')

        if not version or not f or not f.filename:
            flash('Versão e arquivo são obrigatórios.', 'danger')
            return redirect(url_for('download.upload'))

        data = f.read()
        if len(data) > MAX_SIZE:
            flash('Arquivo muito grande. Limite: 150 MB.', 'danger')
            return redirect(url_for('download.upload'))

        sha = _sha512_b64(data)
        key = f'releases/{f.filename}'
        try:
            file_url = r2.upload(data, key, 'application/octet-stream')
            release = AppRelease(
                version     = version,
                description = description,
                filename    = f.filename,
                file_url    = file_url,
                file_sha512 = sha,
                file_size   = len(data),
                platform    = platform,
            )
        except Exception:
            release = AppRelease(
                version     = version,
                description = description,
                filename    = f.filename,
                file_data   = data,
                file_sha512 = sha,
                file_size   = len(data),
                platform    = platform,
            )
        db.session.add(release)
        db.session.commit()
        flash(f'Versão {version} publicada! Os clientes serão notificados automaticamente.', 'success')
        return redirect(url_for('download.upload'))

    releases = AppRelease.query.order_by(AppRelease.uploaded_at.desc()).all()
    return render_template('master/app_upload.html', releases=releases)


@download_bp.route('/master/app/<int:release_id>/excluir', methods=['POST'])
@login_required
@master_required
def excluir_release(release_id):
    release = AppRelease.query.get_or_404(release_id)
    db.session.delete(release)
    db.session.commit()
    flash('Versão removida.', 'info')
    return redirect(url_for('download.upload'))
