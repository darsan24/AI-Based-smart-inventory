"""
Centralized Inventory KPI Calculation Service.

All inventory performance metrics are computed here from raw database data.
This module is the single source of truth — other routes/modules should
import from here rather than re-implementing KPI formulas.

Every formula is documented, date-bounded, and uses cost_price for
financial metrics.
"""

from datetime import timedelta
from sqlalchemy import func, and_, case
from models import db, Product, Sale
from utils.date_utils import get_current_date_ist, get_latest_sale_date


def compute_inventory_kpis(analysis_days=90):
    """
    Computes all inventory performance KPIs for a given analysis period.

    Args:
        analysis_days: Number of trailing days for the analysis window (default 90).

    Returns:
        dict with all KPI values and supporting detail lists.
    """
    today = get_latest_sale_date()
    period_start = today - timedelta(days=analysis_days)

    products = (
        Product.query
        .order_by(db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc())
        .all()
    )

    # ------------------------------------------------------------------
    # 1. Total Inventory Value (at cost)
    # Formula: Σ(cost_price × current_stock)
    # ------------------------------------------------------------------
    total_inventory_cost = sum(
        float(p.cost_price or 0) * p.current_stock
        for p in products
    )
    total_inventory_selling = sum(
        float(p.price or 0) * p.current_stock
        for p in products
    )

    # ------------------------------------------------------------------
    # 2. COGS in the analysis period
    # Formula: Σ(sale.quantity_sold × product.cost_price)
    #          for sales within [period_start, today]
    #
    # We join Sale with Product to get cost_price per unit,
    # then aggregate in SQL to avoid N+1 queries.
    # ------------------------------------------------------------------
    cogs_query = (
        db.session.query(
            func.sum(Sale.quantity_sold * Product.cost_price)
        )
        .join(Product, Sale.product_id == Product.id)
        .filter(Sale.sale_date >= period_start)
        .scalar()
    )
    cogs_period = float(cogs_query or 0)

    # Total revenue in the period (for reference, NOT used in turnover)
    revenue_period = float(
        db.session.query(func.sum(Sale.total_price))
        .filter(Sale.sale_date >= period_start)
        .scalar() or 0
    )

    # Total units sold in the period
    units_sold_period = int(
        db.session.query(func.sum(Sale.quantity_sold))
        .filter(Sale.sale_date >= period_start)
        .scalar() or 0
    )

    # ------------------------------------------------------------------
    # 3. Inventory Turnover Ratio
    # Formula: COGS / Current Inventory at Cost
    #
    # NOTE: Ideally we'd use Average Inventory = (Beginning + Ending) / 2,
    # but we don't have historical inventory snapshots. Current inventory
    # at cost is used as the best available proxy. This is clearly labelled
    # as "approximate" in the UI.
    # ------------------------------------------------------------------
    if total_inventory_cost > 0:
        turnover_ratio = cogs_period / total_inventory_cost
    else:
        turnover_ratio = 0.0

    # ------------------------------------------------------------------
    # 4. Inventory Days (Days Inventory Outstanding)
    # Formula: (Current Inventory at Cost / COGS) × days_in_period
    #
    # Interpretation: How many days of sales the current inventory covers.
    # ------------------------------------------------------------------
    if cogs_period > 0:
        inventory_days = (total_inventory_cost / cogs_period) * analysis_days
    else:
        inventory_days = None  # Cannot compute — no sales in period

    # ------------------------------------------------------------------
    # 5. Dead Stock
    # Definition: Products with current_stock > 0 AND zero sales
    #             in the analysis period.
    # Valuation: cost_price × current_stock
    # ------------------------------------------------------------------
    sold_in_period_ids = set(
        row[0] for row in
        db.session.query(Sale.product_id)
        .filter(Sale.sale_date >= period_start)
        .distinct()
        .all()
    )

    # For dead stock, also find last sale date per product (for display)
    last_sale_subq = (
        db.session.query(
            Sale.product_id,
            func.max(Sale.sale_date).label('last_sale_date')
        )
        .group_by(Sale.product_id)
        .subquery()
    )
    last_sale_map = {
        row.product_id: row.last_sale_date
        for row in db.session.query(last_sale_subq).all()
    }

    dead_stock_products = []
    dead_stock_value = 0.0
    for p in products:
        if p.current_stock > 0 and p.id not in sold_in_period_ids:
            cost = float(p.cost_price or 0)
            locked = cost * p.current_stock
            last_sale = last_sale_map.get(p.id)
            days_since = (today - last_sale).days if last_sale else None
            dead_stock_products.append({
                'product': p,
                'current_stock': p.current_stock,
                'cost_price': cost,
                'locked_value': locked,
                'last_sale_date': last_sale,
                'days_since_sale': days_since,
            })
            dead_stock_value += locked

    # Sort dead stock by locked value descending
    dead_stock_products.sort(key=lambda x: x['locked_value'], reverse=True)

    # ------------------------------------------------------------------
    # 6. Low Stock Items
    # Definition: current_stock > 0 AND current_stock <= reorder_level
    # (Consistent with Product.is_low_stock and global sidebar badge)
    # ------------------------------------------------------------------
    low_stock_products = [
        {
            'product': p,
            'current_stock': p.current_stock,
            'reorder_level': p.reorder_level,
            'shortfall': p.reorder_level - p.current_stock,
        }
        for p in products
        if p.current_stock > 0 and p.current_stock <= p.reorder_level
    ]
    low_stock_products.sort(key=lambda x: x['shortfall'], reverse=True)

    # ------------------------------------------------------------------
    # 7. Out of Stock Items
    # Definition: current_stock == 0
    # ------------------------------------------------------------------
    out_of_stock_products = []
    for p in products:
        if p.current_stock == 0:
            last_sale = last_sale_map.get(p.id)
            out_of_stock_products.append({
                'product': p,
                'last_sale_date': last_sale,
            })

    # ------------------------------------------------------------------
    # 8. Overstock Items
    # Definition: current_stock > maximum_stock
    # ------------------------------------------------------------------
    overstock_products = [
        {
            'product': p,
            'current_stock': p.current_stock,
            'maximum_stock': p.maximum_stock,
            'excess': p.current_stock - p.maximum_stock,
            'excess_value': float(p.cost_price or 0) * (p.current_stock - p.maximum_stock),
        }
        for p in products
        if p.current_stock > p.maximum_stock
    ]
    overstock_products.sort(key=lambda x: x['excess_value'], reverse=True)

    # ------------------------------------------------------------------
    # 9. Fast-Moving & Slow-Moving Products (within analysis period)
    # ------------------------------------------------------------------
    sales_volume = (
        db.session.query(
            Sale.product_id,
            func.sum(Sale.quantity_sold).label('total_qty')
        )
        .filter(Sale.sale_date >= period_start)
        .group_by(Sale.product_id)
        .order_by(func.sum(Sale.quantity_sold).desc())
        .all()
    )

    product_map = {p.id: p for p in products}

    fast_moving = []
    for sv in sales_volume[:5]:
        p = product_map.get(sv.product_id)
        if p:
            fast_moving.append({'product': p, 'qty': int(sv.total_qty)})

    slow_moving = []
    for sv in sales_volume[-5:]:
        p = product_map.get(sv.product_id)
        if p:
            slow_moving.append({'product': p, 'qty': int(sv.total_qty)})
    # Show lowest first for slow movers
    slow_moving.sort(key=lambda x: x['qty'])

    # ------------------------------------------------------------------
    # 10. Inventory Health Score
    # A weighted composite score (0-100) based on objective criteria.
    #
    # Components:
    #   - Turnover Score (30%): ratio normalized against target of 4x
    #   - Stock Availability (25%): % of products that are in-stock
    #   - Dead Stock Penalty (20%): penalize by % of dead stock value
    #   - Low Stock Penalty (15%): penalize by % of products at low stock
    #   - Overstock Penalty (10%): penalize by % of overstock products
    # ------------------------------------------------------------------
    total_products = len(products)

    # Turnover score: 100 if >= 4x, proportional below
    turnover_target = 4.0
    turnover_score = min(turnover_ratio / turnover_target, 1.0) * 100 if turnover_target > 0 else 0

    # Stock availability: % of products with stock > 0
    in_stock_count = sum(1 for p in products if p.current_stock > 0)
    availability_score = (in_stock_count / total_products * 100) if total_products > 0 else 0

    # Dead stock penalty: inverse of dead stock % of total inventory value
    dead_pct = (dead_stock_value / total_inventory_cost * 100) if total_inventory_cost > 0 else 0
    dead_stock_score = max(0, 100 - dead_pct * 5)  # 20% dead stock = 0 score

    # Low stock penalty
    low_pct = (len(low_stock_products) / total_products * 100) if total_products > 0 else 0
    low_stock_score = max(0, 100 - low_pct * 4)

    # Overstock penalty
    over_pct = (len(overstock_products) / total_products * 100) if total_products > 0 else 0
    overstock_score = max(0, 100 - over_pct * 4)

    health_score = round(
        turnover_score * 0.30 +
        availability_score * 0.25 +
        dead_stock_score * 0.20 +
        low_stock_score * 0.15 +
        overstock_score * 0.10
    , 1)

    health_label = 'Excellent' if health_score >= 80 else (
        'Good' if health_score >= 60 else (
            'Fair' if health_score >= 40 else 'Poor'
        )
    )

    # ------------------------------------------------------------------
    # Return all KPIs
    # ------------------------------------------------------------------
    return {
        # Metadata
        'analysis_days': analysis_days,
        'period_start': period_start,
        'period_end': today,
        'total_products': total_products,
        'computed_at': today,

        # Financial KPIs
        'total_inventory_cost': total_inventory_cost,
        'total_inventory_selling': total_inventory_selling,
        'cogs_period': cogs_period,
        'revenue_period': revenue_period,
        'units_sold_period': units_sold_period,

        # Turnover KPIs
        'turnover_ratio': round(turnover_ratio, 2),
        'inventory_days': round(inventory_days, 1) if inventory_days is not None else None,

        # Stock status KPIs
        'low_stock_count': len(low_stock_products),
        'low_stock_products': low_stock_products,
        'out_of_stock_count': len(out_of_stock_products),
        'out_of_stock_products': out_of_stock_products,
        'overstock_count': len(overstock_products),
        'overstock_products': overstock_products,

        # Dead stock KPIs
        'dead_stock_count': len(dead_stock_products),
        'dead_stock_value': dead_stock_value,
        'dead_stock_products': dead_stock_products,

        # Movers
        'fast_moving': fast_moving,
        'slow_moving': slow_moving,

        # Health score
        'health_score': health_score,
        'health_label': health_label,
    }
