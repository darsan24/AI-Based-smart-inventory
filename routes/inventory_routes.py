from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Product, InventoryTransaction, Setting, ReorderRecommendation
from routes.auth_routes import login_required
from utils.email_util import check_and_send_low_stock_alert

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')

@inventory_bp.route('/')
@login_required
def index():
    products = Product.query.order_by(db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc()).all()
    low_stock_enabled = Setting.get_bool('low_stock_alerts', True)
    low_stock_products = [p for p in products if p.is_low_stock] if low_stock_enabled else []
    return render_template(
        'inventory/index.html',
        products=products,
        low_stock_products=low_stock_products
    )

@inventory_bp.route('/stock-in', methods=['POST'])
@login_required
def stock_in():
    product_id = request.form.get('product_id', type=int)
    quantity = request.form.get('quantity', type=int, default=0)
    notes = request.form.get('notes', '').strip()

    if not product_id or quantity <= 0:
        flash('Invalid product or quantity for Stock In operation!', 'warning')
        return redirect(url_for('inventory.index'))

    product = Product.query.get_or_404(product_id)
    product.current_stock += quantity

    tx = InventoryTransaction(
        # pyrefly: ignore [unexpected-keyword]
        product_id=product.id,
        # pyrefly: ignore [unexpected-keyword]
        transaction_type='Stock In',
        # pyrefly: ignore [unexpected-keyword]
        quantity=quantity,
        # pyrefly: ignore [unexpected-keyword]
        notes=notes or f'Restocked {quantity} units'
    )

    try:
        db.session.add(tx)
        db.session.commit()
        flash(f'Stock In successful! Added {quantity} units to "{product.name}". New Stock: {product.current_stock}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing Stock In: {str(e)}', 'danger')

    return redirect(url_for('inventory.index'))

@inventory_bp.route('/stock-out', methods=['POST'])
@login_required
def stock_out():
    product_id = request.form.get('product_id', type=int)
    quantity = request.form.get('quantity', type=int, default=0)
    notes = request.form.get('notes', '').strip()

    if not product_id or quantity <= 0:
        flash('Invalid product or quantity for Stock Out operation!', 'warning')
        return redirect(url_for('inventory.index'))

    product = Product.query.get_or_404(product_id)
    if product.current_stock < quantity:
        flash(f'Insufficient stock! Current stock of "{product.name}" is only {product.current_stock}. Requested: {quantity}.', 'danger')
        return redirect(url_for('inventory.index'))

    was_low_stock = product.is_low_stock
    product.current_stock -= quantity
    
    check_and_send_low_stock_alert(product, was_low_stock)

    tx = InventoryTransaction(
        product_id=product.id,
        transaction_type='Stock Out',
        quantity=-quantity,
        notes=notes or f'Dispatched {quantity} units'
    )

    try:
        db.session.add(tx)
        db.session.commit()
        flash(f'Stock Out successful! Removed {quantity} units from "{product.name}". Remaining Stock: {product.current_stock}', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing Stock Out: {str(e)}', 'danger')

    return redirect(url_for('inventory.index'))

@inventory_bp.route('/modify', methods=['POST'])
@login_required
def modify_stock():
    product_id = request.form.get('product_id', type=int)
    new_stock = request.form.get('new_stock', type=int)
    notes = request.form.get('notes', '').strip()

    if not product_id or new_stock is None or new_stock < 0:
        flash('Invalid product or stock level for modification!', 'warning')
        return redirect(url_for('inventory.index'))

    product = Product.query.get_or_404(product_id)
    old_stock = product.current_stock
    was_low_stock = product.is_low_stock
    diff = new_stock - old_stock

    product.current_stock = new_stock
    
    check_and_send_low_stock_alert(product, was_low_stock)

    tx = InventoryTransaction(
        product_id=product.id,
        # pyrefly: ignore [unexpected-keyword]
        transaction_type='Modification',
        quantity=diff,
        notes=notes or f'Manual inventory balance adjustment from {old_stock} to {new_stock}'
    )

    try:
        db.session.add(tx)
        db.session.commit()
        flash(f'Inventory balance modified for "{product.name}". Updated Stock: {product.current_stock}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error modifying inventory: {str(e)}', 'danger')

    return redirect(url_for('inventory.index'))

@inventory_bp.route('/history')
@login_required
def history():
    transactions = InventoryTransaction.query.order_by(InventoryTransaction.created_at.desc()).all()
    return render_template('inventory/history.html', transactions=transactions)


@inventory_bp.route('/reorder-recommendations')
@login_required
def reorder_recommendations():
    """Lists all products' reorder recommendations, sorted by urgency."""
    # Fetch all recommendations with their products
    recommendations = (
        ReorderRecommendation.query
        .join(Product)
        .order_by(
            # Critical first, then Soon, then Not Urgent
            db.case(
                (ReorderRecommendation.urgency == 'Critical', 0),
                (ReorderRecommendation.urgency == 'Soon', 1),
                else_=2
            ).asc(),
            # Prioritize Class A revenue drivers first, then B, then C
            db.case(
                (Product.abc_class == 'A', 0),
                (Product.abc_class == 'B', 1),
                (Product.abc_class == 'C', 2),
                else_=3
            ).asc(),
            ReorderRecommendation.recommended_quantity.desc()
        )
        .all()
    )

    # Count by urgency for summary stats
    critical_count = sum(1 for r in recommendations if r.urgency == 'Critical')
    soon_count = sum(1 for r in recommendations if r.urgency == 'Soon')
    not_urgent_count = sum(1 for r in recommendations if r.urgency == 'Not Urgent')

    return render_template(
        'inventory/reorder_recommendations.html',
        recommendations=recommendations,
        critical_count=critical_count,
        soon_count=soon_count,
        not_urgent_count=not_urgent_count,
        total_count=len(recommendations),
    )

