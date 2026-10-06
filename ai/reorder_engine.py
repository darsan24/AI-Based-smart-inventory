"""
Reorder Recommendation Engine.

Computes automatic "order this many more units" recommendations
based on forecasted demand, current stock, and safety stock levels.
"""

from datetime import datetime
from models import db, Product, ForecastPrediction, ReorderRecommendation


def generate_reorder_recommendation(db_session, product_id, lead_time_days=7):
    """
    Generates a reorder recommendation for a product based on its most recent
    7-day-horizon forecast.

    Formula:
        recommended_quantity = max(0, forecast_demand_over_lead_time + safety_stock - current_stock)

    Urgency:
        "Critical"   — current_stock <= safety_stock
        "Soon"       — current_stock <= reorder_level
        "Not Urgent" — otherwise

    Replaces any previous recommendation for the same product (delete-then-insert).

    Args:
        db_session: SQLAlchemy session
        product_id: ID of the product to generate recommendation for
        lead_time_days: Number of days of lead time for reorder (default 7)

    Returns:
        The created ReorderRecommendation object, or None if product not found.
    """
    product = db_session.query(Product).get(product_id)
    if not product:
        return None

    # Get the most recent 7-day-horizon forecast
    forecast_7d = (
        db_session.query(ForecastPrediction)
        .filter_by(product_id=product_id, horizon_days=7)
        .order_by(ForecastPrediction.created_at.desc())
        .first()
    )

    if forecast_7d:
        forecast_demand = float(forecast_7d.predicted_demand)
    else:
        # If no 7-day forecast exists, estimate from reorder level
        forecast_demand = float(product.reorder_level)

    # Scale forecast demand to match the lead time
    # The 7-day forecast gives demand over 7 days; scale proportionally if lead_time differs
    forecast_demand_over_lead_time = forecast_demand * (lead_time_days / 7.0)

    current_stock = product.current_stock
    safety_stock = product.safety_stock
    reorder_level = product.reorder_level

    # Compute recommended quantity
    recommended_quantity = max(
        0,
        int(round(forecast_demand_over_lead_time + safety_stock - current_stock))
    )

    # Determine urgency
    if current_stock <= safety_stock:
        urgency = "Critical"
    elif current_stock <= reorder_level:
        urgency = "Soon"
    else:
        urgency = "Not Urgent"

    # Build plain-language reasoning
    reasoning = (
        f"Forecast expects {forecast_demand:.0f} units sold in the next {lead_time_days} days, "
        f"current stock is {current_stock}, safety stock is {safety_stock}. "
    )
    if recommended_quantity > 0:
        reasoning += (
            f"We recommend ordering {recommended_quantity} more units to stay above safety stock."
        )
    else:
        reasoning += (
            f"Current stock is sufficient to cover forecasted demand plus safety stock."
        )

    # Delete any previous recommendation for this product (replace-not-append)
    db_session.query(ReorderRecommendation).filter_by(product_id=product_id).delete()

    # Create new recommendation
    recommendation = ReorderRecommendation(
        product_id=product_id,
        recommended_quantity=recommended_quantity,
        forecast_demand_used=round(forecast_demand_over_lead_time, 2),
        lead_time_days=lead_time_days,
        reasoning=reasoning,
        urgency=urgency,
        generated_at=datetime.utcnow(),
    )
    db_session.add(recommendation)
    db_session.commit()

    return recommendation
