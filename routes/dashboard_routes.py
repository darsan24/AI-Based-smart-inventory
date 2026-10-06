from datetime import datetime, timedelta
from utils.date_utils import get_latest_sale_date
from flask import Blueprint, render_template, jsonify
from models import db, Product, InventoryTransaction, Sale, ForecastPrediction, Setting, ReorderRecommendation
from routes.auth_routes import login_required
from ai.patchtst_model import get_baseline_comparison_summary
from ai.classification_engine import get_classification_matrix

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
@dashboard_bp.route('/dashboard/')
@login_required
def index():
    # 0. Load notification preferences from database
    low_stock_enabled = Setting.get_bool('low_stock_alerts', True)
    out_of_stock_enabled = Setting.get_bool('out_of_stock_alerts', True)

    # 1. Metric Cards Summary
    total_products = Product.query.count()
    products = Product.query.order_by(db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc()).all()
    
    current_inventory = sum(p.current_stock for p in products)
    low_stock_products = [p for p in products if p.is_low_stock] if low_stock_enabled else []
    low_stock_count = len([p for p in products if p.is_low_stock]) if low_stock_enabled else 0
    out_of_stock_count = len([p for p in products if p.current_stock == 0]) if out_of_stock_enabled else 0
    immediate_reorder_count = len([p for p in products if p.current_stock <= p.reorder_level * 0.5]) if low_stock_enabled else 0

    total_sales_sum = db.session.query(db.func.sum(Sale.total_price)).scalar() or 0.0
    total_sales = float(total_sales_sum)

    total_predicted_demand_sum = db.session.query(db.func.sum(ForecastPrediction.predicted_demand)).filter(ForecastPrediction.horizon_days == 15).scalar() or 0.0
    predicted_demand = float(total_predicted_demand_sum)

    # Baseline comparison summary across all products
    baseline_summary = get_baseline_comparison_summary(db.session)

    # ABC / XYZ Classification 9-box matrix summary
    classification_summary = get_classification_matrix(db.session)

    # Reorder Soon KPI: products with Critical or Soon urgency
    try:
        reorder_soon_count = (
            ReorderRecommendation.query
            .filter(ReorderRecommendation.urgency.in_(['Critical', 'Soon']))
            .count()
        )
    except Exception:
        reorder_soon_count = 0

    # 2. Recent Inventory Activities
    recent_activities = InventoryTransaction.query.order_by(InventoryTransaction.created_at.desc()).limit(7).all()

    # 3. Smart Reorder Recommendations
    reorder_recommendations = []
    today = get_latest_sale_date()

    for p in products:
        # Get 15-day forecast prediction
        forecast_15 = ForecastPrediction.query.filter_by(product_id=p.id, horizon_days=15).order_by(ForecastPrediction.created_at.desc()).first()
        pred_demand = float(forecast_15.predicted_demand) if forecast_15 else float(p.reorder_level * 1.5)

        # Formula: Reorder Needed if Current Stock <= Reorder Level OR Current Stock < 15-day demand
        if p.current_stock <= p.reorder_level or p.current_stock < pred_demand:
            # Recommended reorder qty = (Target Stock = Reorder Level * 2 + Forecast Demand) - Current Stock
            recommended_qty = max(int(p.reorder_level * 2 + pred_demand - p.current_stock), p.reorder_level)
            
            # Reorder Urgency / Recommended Date
            days_stock_remaining = max(1, int(p.current_stock / (pred_demand / 15.0 + 0.1)))
            recommended_date = today + timedelta(days=min(days_stock_remaining, 7))

            reorder_recommendations.append({
                'product': p,
                'current_stock': p.current_stock,
                'reorder_level': p.reorder_level,
                'predicted_demand_15d': round(pred_demand, 1),
                'recommended_qty': recommended_qty,
                'recommended_date': recommended_date.strftime('%Y-%m-%d'),
                'urgency': 'CRITICAL' if p.current_stock <= p.reorder_level * 0.5 else 'HIGH'
            })

    # Sort reorder recommendations by urgency
    reorder_recommendations.sort(key=lambda x: (0 if x['urgency'] == 'CRITICAL' else 1, x['current_stock']))

    # 4. Sales Trend Chart Data (Last 14 days)
    fourteen_days_ago = today - timedelta(days=14)
    sales_by_date = db.session.query(
        Sale.sale_date, db.func.sum(Sale.total_price)
    ).filter(Sale.sale_date >= fourteen_days_ago).group_by(Sale.sale_date).order_by(Sale.sale_date.asc()).all()

    trend_dates = [s[0].strftime('%b %d') for s in sales_by_date]
    trend_values = [float(s[1]) for s in sales_by_date]

    # Product Type Stock Breakdown Chart Data (Aggregated by Product Type)
    product_type_stock = db.session.query(
        Product.product_type, db.func.sum(Product.current_stock)
    ).group_by(Product.product_type).order_by(db.func.sum(Product.current_stock).desc()).all()

    product_labels = [p[0] for p in product_type_stock]
    product_values = [int(p[1]) for p in product_type_stock]

    return render_template(
        'dashboard/index.html',
        total_products=total_products,
        current_inventory=current_inventory,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
        immediate_reorder_count=immediate_reorder_count,
        low_stock_products=low_stock_products,
        total_sales=total_sales,
        predicted_demand=predicted_demand,
        baseline_summary=baseline_summary,
        classification_summary=classification_summary,
        recent_activities=recent_activities,
        reorder_recommendations=reorder_recommendations[:5],  # Top 5 urgent
        reorder_soon_count=reorder_soon_count,
        trend_dates=trend_dates,
        trend_values=trend_values,
        product_labels=product_labels,
        product_values=product_values,
        low_stock_enabled=low_stock_enabled,
        out_of_stock_enabled=out_of_stock_enabled
    )
