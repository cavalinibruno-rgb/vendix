from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, abort
from flask_login import login_required, current_user
from app import db
from app.models.app_release import AppRelease
from functools import wraps

download_bp = Blueprint('download', __name__)

MAX_SIZE = 150 * 1024 * 1024  # 150 MB


def master_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_master:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@download_bp.route('/download')
def pagina():
    releases = AppRelease.query.order_by(AppRelease.uploaded_at.desc()).all()
    latest   = releases[0] if releases else None
    return render_template('download.html', latest=latest, releases=releases)


@download_bp.route('/download/<int:release_id>/arquivo')
def arquivo(release_id):
    release = AppRelease.query.get_or_404(release_id)
    return Response(
        release.file_data,
        mimetype='application/vnd.android.package-archive' if release.platform == 'android' else 'application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{release.filename}"'}
    )


@download_bp.route('/master/app/upload', methods=['GET', 'POST'])
@login_required
@master_required
def upload():
    if request.method == 'POST':
        version     = request.form.get('version', '').strip()
        description = request.form.get('description', '').strip()
        platform    = request.form.get('platform', 'android')
        f           = request.files.get('arquivo')

        if not version or not f or not f.filename:
            flash('Versão e arquivo são obrigatórios.', 'danger')
            return redirect(url_for('download.upload'))

        data = f.read()
        if len(data) > MAX_SIZE:
            flash('Arquivo muito grande. Limite: 150 MB.', 'danger')
            return redirect(url_for('download.upload'))

        release = AppRelease(
            version     = version,
            description = description,
            filename    = f.filename,
            file_data   = data,
            file_size   = len(data),
            platform    = platform,
        )
        db.session.add(release)
        db.session.commit()
        flash(f'Versão {version} publicada com sucesso!', 'success')
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
