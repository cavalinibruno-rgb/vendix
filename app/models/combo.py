from app import db

class ComboItem(db.Model):
    __tablename__ = 'combo_items'

    id           = db.Column(db.Integer, primary_key=True)
    combo_id     = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    component_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity     = db.Column(db.Float, nullable=False, default=1)

    component = db.relationship('Product', foreign_keys=[component_id])
