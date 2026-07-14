from app import db
from datetime import datetime

class Ingredient(db.Model):
    __tablename__ = 'ingredients'

    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    name       = db.Column(db.String(128), nullable=False)
    unit       = db.Column(db.String(16), default='un')   # un, g, ml, kg, l
    cost_price = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    usages = db.relationship('ProductIngredient', backref='ingredient',
                             cascade='all, delete-orphan', lazy=True)

    @property
    def formatted_cost(self):
        return f'R$ {self.cost_price:.2f}'.replace('.', ',')


class ProductIngredient(db.Model):
    __tablename__ = 'product_ingredients'

    id            = db.Column(db.Integer, primary_key=True)
    product_id    = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredients.id'), nullable=False)
    quantity      = db.Column(db.Float, default=1.0)
