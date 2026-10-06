from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify
from models import db, Product, Sale, ForecastPrediction, Setting
from routes.auth_routes import login_required

notification_bp = Blueprint('notifications', __name__, url_prefix='/notifications')

def generate_notifications():
    notifications = []
    products = Product.query.order_by(db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc()).all()
    today = datetime.utcnow().date()
    fourteen_days_ago = today - timedelta(days=14)
    twenty_eight_days_ago = today - timedelta(days=28)

    # Respect administrator notification preferences from database
    low_stock_enabled = Setting.get_bool('low_stock_alerts', True)
    out_of_stock_enabled = Setting.get_bool('out_of_stock_alerts', True)

    for p in products:
        # Forecast
        forecast_15 = ForecastPrediction.query.filter_by(product_id=p.id, horizon_days=15).order_by(ForecastPrediction.created_at.desc()).first()
        pred_demand = float(forecast_15.predicted_demand) if forecast_15 else float(p.reorder_level * 1.5)
        
        # Calculate days remaining
        daily_demand = pred_demand / 15.0 if pred_demand > 0 else 0.1
        days_remaining = p.current_stock / daily_demand
        
        # Calculate sales trend
        recent_sales = db.session.query(db.func.sum(Sale.quantity_sold)).filter(Sale.product_id == p.id, Sale.sale_date >= fourteen_days_ago).scalar() or 0
        previous_sales = db.session.query(db.func.sum(Sale.quantity_sold)).filter(Sale.product_id == p.id, Sale.sale_date >= twenty_eight_days_ago, Sale.sale_date < fourteen_days_ago).scalar() or 0
        
        sales_growth = 0
        if previous_sales > 0:
            sales_growth = ((recent_sales - previous_sales) / previous_sales) * 100
        
        notif_id = f"notif_{p.id}_{today.strftime('%Y%m%d')}"

        if p.current_stock == 0:
            if out_of_stock_enabled:
                notifications.append({
                    'id': notif_id + '_crit_0',
                    'type': 'Critical',
                    'priority': 'Critical',
                    'icon': 'fa-triangle-exclamation',
                    'color': 'danger',
                    'product': p.to_dict(),
                    'pred_demand': round(pred_demand, 1),
                    'reason': f"{p.name} is currently out of stock! Immediate restocking is required.",
                    'recommendation': f"Restock at least {max(int(pred_demand + p.reorder_level), p.reorder_level)} units immediately.",
                    'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')
                })
        elif p.current_stock < p.safety_stock:
            if low_stock_enabled:
                notifications.append({
                    'id': notif_id + '_crit_1',
                    'type': 'Critical',
                    'priority': 'Critical',
                    'icon': 'fa-shield-virus',
                    'color': 'danger',
                    'product': p.to_dict(),
                    'pred_demand': round(pred_demand, 1),
                    'reason': f"{p.name} stock ({p.current_stock}) has fallen below the safety stock level ({p.safety_stock}).",
                    'recommendation': "Restock immediately to prevent stockouts.",
                    'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')
                })
        elif days_remaining <= 3:
            if low_stock_enabled:
                notifications.append({
                    'id': notif_id + '_crit_2',
                    'type': 'Critical',
                    'priority': 'Critical',
                    'icon': 'fa-hourglass-end',
                    'color': 'danger',
                    'product': p.to_dict(),
                    'pred_demand': round(pred_demand, 1),
                    'reason': f"{p.name} is predicted to be out of stock within 3 days (Current: {p.current_stock}, Daily Demand: ~{round(daily_demand,1)}).",
                    'recommendation': f"Restock {int(pred_demand)} units immediately.",
                    'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')
                })
        elif p.current_stock <= p.reorder_level:
            if low_stock_enabled:
                notifications.append({
                    'id': notif_id + '_warn_0',
                    'type': 'Warning',
                    'priority': 'Warning',
                    'icon': 'fa-bell',
                    'color': 'warning',
                    'product': p.to_dict(),
                    'pred_demand': round(pred_demand, 1),
                    'reason': f"{p.name} has reached the reorder level ({p.current_stock}/{p.reorder_level}).",
                    'recommendation': f"Consider reordering {int(pred_demand)} units soon.",
                    'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')
                })
        elif p.current_stock < pred_demand:
            if low_stock_enabled:
                notifications.append({
                    'id': notif_id + '_warn_2',
                    'type': 'Warning',
                    'priority': 'Warning',
                    'icon': 'fa-chart-line',
                    'color': 'warning',
                    'product': p.to_dict(),
                    'pred_demand': round(pred_demand, 1),
                    'reason': f"Current inventory ({p.current_stock}) will not meet 15-day forecast demand ({int(pred_demand)}).",
                    'recommendation': "Plan a restock order soon.",
                    'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')
                })
        elif sales_growth > 20:
            notifications.append({
                'id': notif_id + '_warn_1',
                'type': 'Warning',
                'priority': 'Warning',
                'icon': 'fa-arrow-trend-up',
                'color': 'warning',
                'product': p.to_dict(),
                'pred_demand': round(pred_demand, 1),
                'reason': f"{p.name} demand has increased by {int(sales_growth)}% over the last 15 days.",
                'recommendation': f"Ensure sufficient stock. Reorder {int(pred_demand)} units.",
                'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')
            })
        elif recent_sales > 0 and 0 <= sales_growth <= 10:
            notifications.append({
                'id': notif_id + '_ins_0',
                'type': 'AI Insights',
                'priority': 'Low',
                'icon': 'fa-lightbulb',
                'color': 'primary',
                'product': p.to_dict(),
                'pred_demand': round(pred_demand, 1),
                'reason': f"{p.name} demand is stable and predictable.",
                'recommendation': "Maintain current inventory policies.",
                'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')
            })
        elif p.current_stock > p.reorder_level * 1.5:
            notifications.append({
                'id': notif_id + '_hlt_0',
                'type': 'Healthy',
                'priority': 'Low',
                'icon': 'fa-circle-check',
                'color': 'success',
                'product': p.to_dict(),
                'pred_demand': round(pred_demand, 1),
                'reason': f"{p.name} inventory is healthy (Stock: {p.current_stock}).",
                'recommendation': "No action required.",
                'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M')
            })

    # Sort notifications by priority: Critical > Warning > AI Insights > Healthy
    priority_map = {'Critical': 0, 'Warning': 1, 'AI Insights': 2, 'Healthy': 3}
    notifications.sort(key=lambda x: priority_map[x['type']])
    return notifications

@notification_bp.route('/')
@login_required
def index():
    notifications = generate_notifications()
    return render_template('notifications/index.html', notifications=notifications)

@notification_bp.route('/api/list')
@login_required
def api_list():
    notifications = generate_notifications()
    return jsonify(notifications)
