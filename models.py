from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True, default='Admin User')
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), default='admin')
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        if not password:
            raise ValueError("Password cannot be empty.")
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash or not password:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'name': self.name or 'Admin User',
            'email': self.email,
            'role': self.role,
            'is_active': bool(self.is_active),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else ''
        }

    def __repr__(self):
        return f'<User {self.username}>'


class Setting(db.Model):
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls, key, default=None):
        try:
            item = cls.query.filter_by(key=key).first()
            if item:
                return item.value
        except Exception:
            pass
        return default

    @classmethod
    def get_bool(cls, key, default=True):
        val = cls.get(key, None)
        if val is None:
            if key.endswith('_enabled'):
                alt_key = key[:-8]
            else:
                alt_key = key + '_enabled'
            val = cls.get(alt_key, None)
        if val is None:
            return default
        return str(val).strip().lower() in ('true', '1', 'yes', 'on')

    @classmethod
    def set(cls, key, value):
        try:
            item = cls.query.filter_by(key=key).first()
            if not item:
                item = cls(key=key, value=str(value))
                db.session.add(item)
            else:
                item.value = str(value)
                item.updated_at = datetime.utcnow()
            db.session.commit()
            return item
        except Exception:
            db.session.rollback()
            return None


class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    product_id_str = db.Column(db.String(30), unique=True, nullable=False) # e.g. PRD-1001
    product_type = db.Column(db.String(80), nullable=False, default='Laptop') # e.g. Laptop, Server, Mouse
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    brand = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0.00) # Treated as Selling Price
    cost_price = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    mrp = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    currency = db.Column(db.String(10), nullable=False, default='INR')
    current_stock = db.Column(db.Integer, nullable=False, default=0)
    reorder_level = db.Column(db.Integer, nullable=False, default=10)
    safety_stock = db.Column(db.Integer, nullable=False, default=5)
    maximum_stock = db.Column(db.Integer, nullable=False, default=100)
    unit = db.Column(db.String(20), nullable=False, default='Nos')
    sku = db.Column(db.String(50), unique=True)
    supplier_name = db.Column(db.String(120))
    description = db.Column(db.Text)

    # ABC / XYZ Inventory Classification fields
    abc_class = db.Column(db.String(1), nullable=True)                  # "A", "B", "C" (Revenue based)
    xyz_class = db.Column(db.String(1), nullable=True)                  # "X", "Y", "Z" (Demand variability based)
    revenue_contribution_percent = db.Column(db.Numeric(5, 2), nullable=True) # Product revenue share %
    demand_variability = db.Column(db.Numeric(6, 4), nullable=True)     # Raw Coefficient of Variation (CV)
    classification_updated_at = db.Column(db.DateTime, nullable=True)

    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    transactions = db.relationship('InventoryTransaction', backref='product', cascade='all, delete-orphan', lazy=True)
    sales = db.relationship('Sale', backref='product', cascade='all, delete-orphan', lazy=True)
    predictions = db.relationship('ForecastPrediction', backref='product', cascade='all, delete-orphan', lazy=True)

    @property
    def is_low_stock(self):
        return self.current_stock <= self.reorder_level

    @property
    def combined_class(self):
        if self.abc_class and self.xyz_class:
            return f"{self.abc_class}{self.xyz_class}"
        return None

    def to_dict(self):
        return {
            'id': self.id,
            'product_id_str': self.product_id_str,
            'product_type': self.product_type,
            'name': self.name,
            'category': self.category,
            'brand': self.brand,
            'price': float(self.price),
            'selling_price': float(self.price),
            'cost_price': float(self.cost_price) if self.cost_price else 0.0,
            'mrp': float(self.mrp) if self.mrp else 0.0,
            'currency': self.currency,
            'current_stock': self.current_stock,
            'reorder_level': self.reorder_level,
            'safety_stock': self.safety_stock,
            'maximum_stock': self.maximum_stock,
            'unit': self.unit,
            'sku': self.sku,
            'supplier_name': self.supplier_name,
            'description': self.description,
            'abc_class': self.abc_class,
            'xyz_class': self.xyz_class,
            'combined_class': self.combined_class,
            'revenue_contribution_percent': float(self.revenue_contribution_percent) if self.revenue_contribution_percent is not None else 0.0,
            'demand_variability': float(self.demand_variability) if self.demand_variability is not None else None,
            'classification_updated_at': self.classification_updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.classification_updated_at else '',
            'date_added': self.date_added.strftime('%Y-%m-%d %H:%M') if self.date_added else '',
            'last_updated': self.last_updated.strftime('%Y-%m-%d %H:%M:%S') if self.last_updated else '',
            'is_low_stock': self.is_low_stock
        }

    def __repr__(self):
        return f'<Product {self.name} ({self.product_type} - {self.brand})>'


class InventoryTransaction(db.Model):
    __tablename__ = 'inventory_transactions'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'Stock In', 'Stock Out', 'Modification'
    quantity = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else 'N/A',
            'product_id_str': self.product.product_id_str if self.product else 'N/A',
            'transaction_type': self.transaction_type,
            'quantity': self.quantity,
            'notes': self.notes,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else ''
        }


class Sale(db.Model):
    __tablename__ = 'sales'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(50), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity_sold = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    sale_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else 'N/A',
            'product_id_str': self.product.product_id_str if self.product else 'N/A',
            'quantity_sold': self.quantity_sold,
            'total_price': float(self.total_price),
            'sale_date': self.sale_date.strftime('%Y-%m-%d') if self.sale_date else '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else ''
        }


class ForecastPrediction(db.Model):
    __tablename__ = 'forecast_predictions'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    forecast_date = db.Column(db.Date, nullable=False)           # Target date (today + horizon)
    horizon_days = db.Column(db.Integer, nullable=False)          # 7, 15, 30
    predicted_demand = db.Column(db.Numeric(10, 2), nullable=False)
    confidence_lower = db.Column(db.Numeric(10, 2))
    confidence_upper = db.Column(db.Numeric(10, 2))
    forecast_generation_date = db.Column(db.Date, nullable=True)  # When forecast was generated (IST)
    last_historical_date = db.Column(db.Date, nullable=True)      # Latest sales date used
    model_method = db.Column(db.String(50), nullable=True)        # "PatchTST" / "Statistical Fallback" / "Insufficient Data"
    model_mae = db.Column(db.Numeric(10, 4), nullable=True)       # Validation MAE
    model_rmse = db.Column(db.Numeric(10, 4), nullable=True)      # Validation RMSE
    data_confidence = db.Column(db.String(20), nullable=True)     # "High" / "Medium" / "Low"
    explanation_summary = db.Column(db.Text, nullable=True)       # Human-readable explanation sentence
    top_factors = db.Column(db.Text, nullable=True)               # JSON-encoded list of {"factor": ..., "impact_percent": ...}
    baseline_predicted_demand = db.Column(db.Numeric(10, 2), nullable=True) # Simple moving-average baseline prediction
    baseline_method = db.Column(db.String(50), nullable=True)     # "14-Day Moving Average"
    baseline_mae = db.Column(db.Numeric(10, 4), nullable=True)    # Baseline validation MAE
    baseline_rmse = db.Column(db.Numeric(10, 4), nullable=True)   # Baseline validation RMSE
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        import json
        from utils.date_utils import format_date_display

        # Safely parse top_factors JSON
        parsed_factors = []
        if self.top_factors:
            try:
                parsed_factors = json.loads(self.top_factors)
                if not isinstance(parsed_factors, list):
                    parsed_factors = []
            except (json.JSONDecodeError, TypeError, ValueError):
                parsed_factors = []

        # Calculate improvement percent vs simple baseline
        improvement_percent = None
        if self.baseline_mae is not None and self.model_mae is not None:
            try:
                b_mae = float(self.baseline_mae)
                m_mae = float(self.model_mae)
                if b_mae > 0:
                    improvement_percent = round(((b_mae - m_mae) / b_mae) * 100, 2)
            except (ZeroDivisionError, ValueError, TypeError):
                improvement_percent = None

        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else 'N/A',
            'product_id_str': self.product.product_id_str if self.product else 'N/A',
            'forecast_date': self.forecast_date.strftime('%Y-%m-%d') if self.forecast_date else '',
            'forecast_date_display': format_date_display(self.forecast_date),
            'horizon_days': self.horizon_days,
            'predicted_demand': float(self.predicted_demand),
            'confidence_lower': float(self.confidence_lower) if self.confidence_lower is not None else float(self.predicted_demand * 0.9),
            'confidence_upper': float(self.confidence_upper) if self.confidence_upper is not None else float(self.predicted_demand * 1.1),
            'forecast_generation_date': format_date_display(self.forecast_generation_date),
            'last_historical_date': format_date_display(self.last_historical_date),
            'model_method': self.model_method or 'PatchTST',
            'model_mae': float(self.model_mae) if self.model_mae is not None else None,
            'model_rmse': float(self.model_rmse) if self.model_rmse is not None else None,
            'data_confidence': self.data_confidence or 'Medium',
            'explanation_summary': self.explanation_summary or '',
            'top_factors': parsed_factors,
            'baseline_predicted_demand': float(self.baseline_predicted_demand) if self.baseline_predicted_demand is not None else None,
            'baseline_method': self.baseline_method or '14-Day Moving Average',
            'baseline_mae': float(self.baseline_mae) if self.baseline_mae is not None else None,
            'baseline_rmse': float(self.baseline_rmse) if self.baseline_rmse is not None else None,
            'improvement_percent': improvement_percent,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else ''
        }


class ReorderRecommendation(db.Model):
    __tablename__ = 'reorder_recommendations'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    recommended_quantity = db.Column(db.Integer, nullable=False)
    forecast_demand_used = db.Column(db.Numeric(10, 2), nullable=False)
    lead_time_days = db.Column(db.Integer, nullable=False, default=7)
    reasoning = db.Column(db.Text)
    urgency = db.Column(db.String(20))  # "Critical" / "Soon" / "Not Urgent"
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product', backref='reorder_recommendations')

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else 'N/A',
            'product_id_str': self.product.product_id_str if self.product else 'N/A',
            'recommended_quantity': self.recommended_quantity,
            'forecast_demand_used': float(self.forecast_demand_used),
            'lead_time_days': self.lead_time_days,
            'reasoning': self.reasoning or '',
            'urgency': self.urgency or 'Not Urgent',
            'generated_at': self.generated_at.strftime('%Y-%m-%d %H:%M:%S') if self.generated_at else ''
        }
