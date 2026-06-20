from app import db
from datetime import datetime

class ProductType(db.Model):
    __tablename__ = 'product_types'

    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    name       = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    products = db.relationship('Product', backref='type', lazy=True)

class Brand(db.Model):
    __tablename__ = 'brands'

    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    name       = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    products = db.relationship('Product', backref='brand', lazy=True)

class Product(db.Model):
    __tablename__ = 'products'

    id             = db.Column(db.Integer, primary_key=True)
    tenant_id      = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    type_id        = db.Column(db.Integer, db.ForeignKey('product_types.id'), nullable=True)
    brand_id       = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=True)
    name           = db.Column(db.String(128), nullable=False)
    description    = db.Column(db.Text)
    sale_price     = db.Column(db.Float, default=0)
    cost_price     = db.Column(db.Float, default=0)
    stock_quantity = db.Column(db.Integer, default=0)
    min_stock      = db.Column(db.Integer, default=0)
    active         = db.Column(db.Boolean, default=True)
    image_path     = db.Column(db.String(256))
    image_data     = db.Column(db.LargeBinary)
    image_mime     = db.Column(db.String(32))
    created_at     = db.Column(db.DateTime, default=datetime.now)
