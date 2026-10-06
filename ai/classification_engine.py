"""
ABC / XYZ Inventory Classification Engine for Smart Inventory AI.

ABC Analysis (Revenue Contribution):
- Class A: Top revenue drivers accounting for up to 80% of cumulative revenue.
- Class B: Moderate revenue drivers accounting for the next 15% (80% - 95%).
- Class C: Low revenue drivers accounting for the remaining 5% (95% - 100%).

XYZ Analysis (Demand Variability / Predictability):
- Class X: Stable, steady demand (Coefficient of Variation CV < 0.50).
- Class Y: Moderate variability / seasonal demand (0.50 <= CV < 1.00).
- Class Z: Highly volatile / erratic demand (CV >= 1.00).

Combined 9-Box Grid: AX, AY, AZ, BX, BY, BZ, CX, CY, CZ.
"""

from datetime import datetime
import numpy as np
from models import Product, Sale

# Configurable Threshold Constants
ABC_THRESHOLD_A = 0.80  # Cumulative revenue <= 80% -> Class A
ABC_THRESHOLD_B = 0.95  # Cumulative revenue <= 95% -> Class B
XYZ_THRESHOLD_X = 0.50  # CV < 0.50 -> Class X (Steady)
XYZ_THRESHOLD_Y = 1.00  # 0.50 <= CV < 1.00 -> Class Y (Moderate), >= 1.00 -> Class Z (Erratic)


def classify_all_products(db_session):
    """
    Computes ABC and XYZ classification for all products in the database.
    Updates Product records with abc_class, xyz_class, revenue_contribution_percent,
    demand_variability, and classification_updated_at.

    Returns:
        dict: Summary of classification results and counts.
    """
    products = db_session.query(Product).all()
    if not products:
        return {
            "total_products": 0,
            "abc_counts": {"A": 0, "B": 0, "C": 0},
            "xyz_counts": {"X": 0, "Y": 0, "Z": 0, "None": 0},
            "matrix_9box": {}
        }

    # Fetch all sales records and aggregate by product
    sales = db_session.query(Sale).all()

    # Map product_id -> list of sales records
    sales_by_product = {}
    for p in products:
        sales_by_product[p.id] = []

    for s in sales:
        if s.product_id in sales_by_product:
            sales_by_product[s.product_id].append(s)

    # 1. Compute Total Revenue per Product
    product_revenue = {}
    for p in products:
        p_sales = sales_by_product[p.id]
        rev = sum(float(s.total_price) for s in p_sales)
        product_revenue[p.id] = rev

    total_revenue_all = sum(product_revenue.values())

    # 2. ABC Classification (Sorted by Revenue Descending)
    sorted_by_revenue = sorted(products, key=lambda p: product_revenue[p.id], reverse=True)

    cumulative_rev = 0.0
    for idx, p in enumerate(sorted_by_revenue):
        p_rev = product_revenue[p.id]

        if total_revenue_all > 0:
            p_share_pct = round((p_rev / total_revenue_all) * 100.0, 2)
            cumulative_rev += p_rev
            cumulative_ratio = cumulative_rev / total_revenue_all

            # Assign ABC class based on cumulative revenue share
            if cumulative_ratio <= ABC_THRESHOLD_A or idx == 0:
                p.abc_class = "A"
            elif cumulative_ratio <= ABC_THRESHOLD_B:
                p.abc_class = "B"
            else:
                p.abc_class = "C"

            p.revenue_contribution_percent = p_share_pct
        else:
            p.abc_class = "C"
            p.revenue_contribution_percent = 0.0

    # 3. XYZ Classification (Demand Variability / Coefficient of Variation)
    now = datetime.utcnow()

    for p in products:
        p_sales = sales_by_product[p.id]

        # Extract daily sales quantities
        daily_qtys = [float(s.quantity_sold) for s in p_sales]

        if len(daily_qtys) >= 2:
            mean_qty = float(np.mean(daily_qtys))
            std_qty = float(np.std(daily_qtys, ddof=1))

            if mean_qty > 0:
                cv = std_qty / mean_qty
                p.demand_variability = round(cv, 4)

                if cv < XYZ_THRESHOLD_X:
                    p.xyz_class = "X"
                elif cv < XYZ_THRESHOLD_Y:
                    p.xyz_class = "Y"
                else:
                    p.xyz_class = "Z"
            else:
                p.xyz_class = None
                p.demand_variability = None
        else:
            # Edge case: zero sales or single data point -> CV undefined
            p.xyz_class = None
            p.demand_variability = None

        p.classification_updated_at = now

    db_session.commit()

    # Build summary stats
    abc_counts = {"A": 0, "B": 0, "C": 0}
    xyz_counts = {"X": 0, "Y": 0, "Z": 0, "None": 0}
    matrix_9box = {
        "AX": 0, "AY": 0, "AZ": 0,
        "BX": 0, "BY": 0, "BZ": 0,
        "CX": 0, "CY": 0, "CZ": 0,
        "Unclassified": 0
    }

    for p in products:
        if p.abc_class in abc_counts:
            abc_counts[p.abc_class] += 1

        if p.xyz_class in xyz_counts:
            xyz_counts[p.xyz_class] += 1
        else:
            xyz_counts["None"] += 1

        comb = p.combined_class
        if comb in matrix_9box:
            matrix_9box[comb] += 1
        else:
            matrix_9box["Unclassified"] += 1

    return {
        "total_products": len(products),
        "total_revenue": round(total_revenue_all, 2),
        "abc_counts": abc_counts,
        "xyz_counts": xyz_counts,
        "matrix_9box": matrix_9box
    }


def get_classification_matrix(db_session):
    """
    Returns the current 9-box grid count and percentage distribution for dashboard visualization.
    """
    products = db_session.query(Product).all()
    total = len(products) if products else 0

    matrix = {
        "AX": 0, "AY": 0, "AZ": 0,
        "BX": 0, "BY": 0, "BZ": 0,
        "CX": 0, "CY": 0, "CZ": 0,
        "Unclassified": 0
    }

    abc_totals = {"A": 0, "B": 0, "C": 0}
    xyz_totals = {"X": 0, "Y": 0, "Z": 0}

    for p in products:
        comb = p.combined_class
        if comb in matrix:
            matrix[comb] += 1
        else:
            matrix["Unclassified"] += 1

        if p.abc_class in abc_totals:
            abc_totals[p.abc_class] += 1
        if p.xyz_class in xyz_totals:
            xyz_totals[p.xyz_class] += 1

    return {
        "matrix": matrix,
        "abc_totals": abc_totals,
        "xyz_totals": xyz_totals,
        "total_products": total
    }
