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
    sale_price       = db.Column(db.Float, default=0)
    sale_price_card  = db.Column(db.Float, default=0)
    sale_price_event = db.Column(db.Float, default=0)
    cost_price       = db.Column(db.Float, default=0)
    stock_quantity = db.Column(db.Integer, default=0)
    min_stock      = db.Column(db.Integer, default=0)
    active         = db.Column(db.Boolean, default=True)
    image_path     = db.Column(db.String(256))
    image_url      = db.Column(db.String(512))
    image_data     = db.Column(db.LargeBinary)
    image_mime     = db.Column(db.String(32))
    thumbnail_data = db.Column(db.LargeBinary)
    created_at     = db.Column(db.DateTime, default=datetime.now)

    pack_parent_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    pack_qty       = db.Column(db.Integer, nullable=True)  # unidades contidas neste pack

    pack_parent = db.relationship('Product', foreign_keys=[pack_parent_id], remote_side='Product.id',
                                  backref=db.backref('pack_children', lazy=True))

    combo_items = db.relationship('ComboItem', foreign_keys='ComboItem.combo_id',
                                  backref='combo_product', cascade='all, delete-orphan', lazy=True)

    @property
    def effective_stock(self):
        """Para pack: estoque do pai ÷ unidades. Para unitário/combo: stock_quantity normal."""
        if self.pack_parent_id and self.pack_qty and self.pack_qty > 0:
            parent_stock = self.pack_parent.stock_quantity if self.pack_parent else 0
            return parent_stock // self.pack_qty
        return self.stock_quantity

    @property
    def pack_remainder(self):
        """Unidades restantes do pai que não completam um pack."""
        if self.pack_parent_id and self.pack_qty and self.pack_qty > 0:
            parent_stock = self.pack_parent.stock_quantity if self.pack_parent else 0
            return parent_stock % self.pack_qty
        return 0
