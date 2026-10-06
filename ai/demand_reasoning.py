"""
AI Demand Reasoning Module.

Generates contextual, data-driven explanations for demand forecasts.
All date operations use IST (Asia/Kolkata) via the centralized date utility.
"""

from datetime import timedelta
from sqlalchemy import func
from models import Sale
from utils.date_utils import get_current_date_ist, get_latest_sale_date


def generate_ai_demand_reason(product, forecast_15d_value, shap_data, db_session):
    """
    Generates an AI reasoning summary for a product's demand forecast.

    Returns a dict with:
      - explanation: natural language reasoning
      - recommendation: action, date, risk, confidence info
      - positive_factors: list of favorable signals
      - negative_factors: list of unfavorable signals
    """
    today = get_latest_sale_date(db_session)
    thirty_days_ago = today - timedelta(days=30)
    seven_days_ago = today - timedelta(days=7)

    # 1. Fetch actual sales data
    sales_30d = db_session.query(func.sum(Sale.quantity_sold)).filter(
        Sale.product_id == product.id,
        Sale.sale_date >= thirty_days_ago
    ).scalar() or 0

    sales_7d = db_session.query(func.sum(Sale.quantity_sold)).filter(
        Sale.product_id == product.id,
        Sale.sale_date >= seven_days_ago
    ).scalar() or 0

    # Count actual sale days for better averages
    sale_days_30d = db_session.query(func.count(Sale.id)).filter(
        Sale.product_id == product.id,
        Sale.sale_date >= thirty_days_ago
    ).scalar() or 0

    # Calculate trends
    avg_30d = sales_30d / 30.0
    avg_7d = sales_7d / 7.0

    trend_pct = 0
    trend_type = "stable"
    if avg_30d > 0:
        trend_pct = ((avg_7d - avg_30d) / avg_30d) * 100
        if trend_pct >= 10:
            trend_type = "increasing"
        elif trend_pct <= -10:
            trend_type = "decreasing"

    # 2. Risk Level — based on actual data, not fabricated confidence
    risk_level = "Low"
    risk_color = "success"

    current_stock = product.current_stock
    reorder_level = product.reorder_level

    if current_stock == 0 or forecast_15d_value > (current_stock * 1.5):
        risk_level = "High"
        risk_color = "danger"
    elif forecast_15d_value > current_stock or current_stock <= reorder_level:
        risk_level = "Medium"
        risk_color = "warning"

    # 3. Dynamic Explanation Text
    trend_str = ""
    if trend_type == "increasing":
        trend_str = (
            f"Demand is expected to increase because this product has shown a "
            f"{abs(round(trend_pct))}% increase in sales velocity over the recent "
            f"7 days compared to the 30-day average."
        )
    elif trend_type == "decreasing":
        trend_str = (
            f"Demand is predicted to decrease because sales have declined by "
            f"{abs(round(trend_pct))}% in the short term."
        )
    else:
        trend_str = "Sales have remained relatively stable during the last month."

    stock_str = ""
    if current_stock < forecast_15d_value:
        stock_str = (
            "Current inventory is below the predicted 15-day demand, "
            "making immediate restocking highly recommended."
        )
    elif current_stock <= reorder_level:
        stock_str = (
            "Inventory levels have breached the safety reorder threshold. "
            "Replenishment is advised."
        )
    else:
        stock_str = (
            "Current inventory levels are sufficient to cover forecasted demand, "
            "and no immediate restocking is required."
        )

    top_feature = "market factors"
    if shap_data and 'feature_contributions' in shap_data and len(shap_data['feature_contributions']) > 0:
        top_feature = shap_data['feature_contributions'][0]['feature'].lower()

    explanation = (
        f"{trend_str} {stock_str} "
        f"The AI model weighted '{top_feature}' as the primary contributing factor for this forecast."
    )

    # 4. Recommendation
    recommended_qty = 0
    if current_stock < forecast_15d_value:
        recommended_qty = int(forecast_15d_value - current_stock + (reorder_level * 0.5))
    elif current_stock <= reorder_level:
        recommended_qty = int(reorder_level * 1.5)

    suggested_date = today.strftime("%d %b %Y")
    if risk_level == "Medium" and current_stock > 0:
        suggested_date = (today + timedelta(days=3)).strftime("%d %b %Y")
    elif risk_level == "Low":
        suggested_date = "N/A"

    # Data-driven confidence: based on data availability, not hardcoded formula
    confidence_label = "Medium"
    if sale_days_30d >= 20 and sales_30d > 0:
        confidence_label = "High"
    elif sale_days_30d >= 10:
        confidence_label = "Medium"
    else:
        confidence_label = "Low"

    recommendation = {
        "action": f"Reorder {recommended_qty} Units" if recommended_qty > 0 else "Monitor Stock",
        "date": suggested_date,
        "risk": risk_level,
        "risk_color": risk_color,
        "confidence": confidence_label
    }

    # 5. Positive / Negative Factors
    positive_factors = []
    negative_factors = []

    if trend_type == "increasing":
        positive_factors.append(f"Strong upward sales trend (+{abs(round(trend_pct))}%)")
    elif trend_type == "decreasing":
        negative_factors.append(f"Recent decline in sales velocity (-{abs(round(trend_pct))}%)")

    if current_stock > reorder_level and current_stock >= forecast_15d_value:
        positive_factors.append("Healthy inventory coverage")
    elif current_stock <= reorder_level:
        negative_factors.append("Stock below safety reorder level")

    if forecast_15d_value > current_stock:
        negative_factors.append("Forecasted demand exceeds current inventory")

    if confidence_label == "High":
        positive_factors.append("Sufficient historical data for reliable forecast")
    elif confidence_label == "Low":
        negative_factors.append("Limited sales history reduces forecast reliability")

    if shap_data and 'feature_contributions' in shap_data:
        for fc in shap_data['feature_contributions']:
            if fc['impact'] == 'Negative' and len(negative_factors) < 3:
                negative_factors.append(f"AI detected penalty from {fc['feature'].lower()}")
            elif fc['impact'] == 'Positive' and len(positive_factors) < 3:
                positive_factors.append(f"AI boosted by {fc['feature'].lower()}")

    return {
        "explanation": explanation,
        "recommendation": recommendation,
        "positive_factors": positive_factors[:3],
        "negative_factors": negative_factors[:3]
    }
