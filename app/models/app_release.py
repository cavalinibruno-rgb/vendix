from app import db
from datetime import datetime

class AppRelease(db.Model):
    __tablename__ = 'app_releases'

    id          = db.Column(db.Integer, primary_key=True)
    version     = db.Column(db.String(32), nullable=False)
    description = db.Column(db.Text, nullable=True)
    filename    = db.Column(db.String(256), nullable=False)
    file_url    = db.Column(db.String(512), nullable=True)
    file_data   = db.Column(db.LargeBinary, nullable=True)
    file_size   = db.Column(db.Integer, nullable=False)
    platform    = db.Column(db.String(16), default='android')  # android | ios | windows
    uploaded_at = db.Column(db.DateTime, default=datetime.now)
