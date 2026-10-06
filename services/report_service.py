"""
Centralized Reporting Service for Smart Inventory AI.

Provides consistent filtering, data enrichment, natural sorting,
and unified date handling across Web Previews, CSV Exports, and PDF Exports.
"""

from sqlalchemy import func, or_
from models import db, Product, Sale, ForecastPrediction
from utils.date_utils import (
    get_current_date_ist,
    get_forecast_target_date,
    format_date_display,
    format_date_iso
)


def get_report_filter_options():
    """
    Returns distinct product types, categories, and brands for report filter dropdowns.
    """
    product_types = [
        r[0] for r in db.session.query(Product.product_type).distinct().order_by(Product.product_type.asc()).all() if r[0]
    ]
    categories = [
        r[0] for r in db.session.query(Product.category).distinct().order_by(Product.category.asc()).all() if r[0]
    ]
    brands = [
        r[0] for r in db.session.query(Product.brand).distinct().order_by(Product.brand.asc()).all() if r[0]
    ]
    return {
        'product_types': product_types,
        'categories': categories,
        'brands': brands,
    }


def get_filtered_forecast_report(horizon=None, category=None, brand=None, product_type=None, search_query=None):
    """
    Retrieves filtered ForecastPrediction records with joined Product data,
    ordered naturally by product ID and forecast horizon.
    """
    query = db.session.query(ForecastPrediction).join(Product, ForecastPrediction.product_id == Product.id)

    if horizon and str(horizon).isdigit() and int(horizon) in (7, 15, 30):
        query = query.filter(ForecastPrediction.horizon_days == int(horizon))

    if category and category.strip() and category.lower() != 'all':
        query = query.filter(Product.category == category.strip())

    if brand and brand.strip() and brand.lower() != 'all':
        query = query.filter(Product.brand == brand.strip())

    if product_type and product_type.strip() and product_type.lower() != 'all':
        query = query.filter(Product.product_type == product_type.strip())

    if search_query and search_query.strip():
        q = f"%{search_query.strip()}%"
        query = query.filter(
            or_(
                Product.name.ilike(q),
                Product.product_id_str.ilike(q),
                Product.brand.ilike(q),
                Product.category.ilike(q)
            )
        )

    # Order naturally: PRD numeric index, then horizon ascending
    forecasts = query.order_by(
        db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc(),
        ForecastPrediction.horizon_days.asc()
    ).all()

    # Calculate summary metadata
    latest_gen_date = None
    if forecasts:
        gen_dates = [f.forecast_generation_date for f in forecasts if f.forecast_generation_date]
        if gen_dates:
            latest_gen_date = max(gen_dates)

    unique_products_count = len(set(f.product_id for f in forecasts))
    avg_predicted_demand = round(
        sum(float(f.predicted_demand) for f in forecasts) / len(forecasts), 1
    ) if forecasts else 0.0

    return {
        'forecasts': forecasts,
        'total_records': len(forecasts),
        'unique_products_count': unique_products_count,
        'avg_predicted_demand': avg_predicted_demand,
        'latest_gen_date': latest_gen_date,
        'latest_gen_date_display': format_date_display(latest_gen_date) if latest_gen_date else format_date_display(get_current_date_ist()),
    }


def get_filtered_inventory_report(category=None, brand=None, product_type=None, search_query=None):
    """
    Retrieves filtered Product records for the inventory report.
    """
    query = Product.query

    if category and category.strip() and category.lower() != 'all':
        query = query.filter(Product.category == category.strip())

    if brand and brand.strip() and brand.lower() != 'all':
        query = query.filter(Product.brand == brand.strip())

    if product_type and product_type.strip() and product_type.lower() != 'all':
        query = query.filter(Product.product_type == product_type.strip())

    if search_query and search_query.strip():
        q = f"%{search_query.strip()}%"
        query = query.filter(
            or_(
                Product.name.ilike(q),
                Product.product_id_str.ilike(q),
                Product.brand.ilike(q),
                Product.category.ilike(q)
            )
        )

    products = query.order_by(
        db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc()
    ).all()

    return products


def get_filtered_sales_report(category=None, brand=None, product_type=None, search_query=None, limit=200):
    """
    Retrieves filtered Sale records with joined Product data.
    """
    query = db.session.query(Sale).join(Product, Sale.product_id == Product.id)

    if category and category.strip() and category.lower() != 'all':
        query = query.filter(Product.category == category.strip())

    if brand and brand.strip() and brand.lower() != 'all':
        query = query.filter(Product.brand == brand.strip())

    if product_type and product_type.strip() and product_type.lower() != 'all':
        query = query.filter(Product.product_type == product_type.strip())

    if search_query and search_query.strip():
        q = f"%{search_query.strip()}%"
        query = query.filter(
            or_(
                Product.name.ilike(q),
                Product.product_id_str.ilike(q),
                Product.brand.ilike(q),
                Product.category.ilike(q)
            )
        )

    sales = query.order_by(Sale.sale_date.desc()).limit(limit).all()
    return sales


def get_filtered_low_stock_report(category=None, brand=None, product_type=None, search_query=None):
    """
    Retrieves filtered Products that are at or below their reorder level.
    """
    query = Product.query.filter(Product.current_stock <= Product.reorder_level)

    if category and category.strip() and category.lower() != 'all':
        query = query.filter(Product.category == category.strip())

    if brand and brand.strip() and brand.lower() != 'all':
        query = query.filter(Product.brand == brand.strip())

    if product_type and product_type.strip() and product_type.lower() != 'all':
        query = query.filter(Product.product_type == product_type.strip())

    if search_query and search_query.strip():
        q = f"%{search_query.strip()}%"
        query = query.filter(
            or_(
                Product.name.ilike(q),
                Product.product_id_str.ilike(q),
                Product.brand.ilike(q),
                Product.category.ilike(q)
            )
        )

    low_stock = query.order_by(
        (Product.reorder_level - Product.current_stock).desc()
    ).all()

    return low_stock
