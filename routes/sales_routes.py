import os
from datetime import datetime, timedelta
import pandas as pd
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from sqlalchemy import func, desc, asc, cast, Integer, extract
from models import db, Product, Sale, InventoryTransaction
from routes.auth_routes import login_required
from utils.email_util import check_and_send_low_stock_alert
from utils.date_utils import get_latest_sale_date
from ai.patchtst_model import train_and_forecast_product

sales_bp = Blueprint('sales', __name__, url_prefix='/sales')

# ─────────────────────────────────────────────────────────
# Existing Routes (unchanged)
# ─────────────────────────────────────────────────────────

@sales_bp.route('/')
@login_required
def index():
    return redirect(url_for('sales.entry'))

@sales_bp.route('/entry')
@login_required
def entry():
    products = Product.query.order_by(db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc()).all()
    return render_template('sales/entry.html', products=products)

@sales_bp.route('/history')
@login_required
def history():
    sales = Sale.query.order_by(Sale.sale_date.desc(), Sale.created_at.desc()).all()
    return render_template('sales/history.html', sales=sales)

@sales_bp.route('/add', methods=['POST'])
@login_required
def add_sale():
    product_id = request.form.get('product_id', type=int)
    quantity_sold = request.form.get('quantity_sold', type=int, default=0)
    sale_date_str = request.form.get('sale_date', '').strip()

    if not product_id or quantity_sold <= 0 or not sale_date_str:
        flash('Product, valid quantity, and sale date are required!', 'warning')
        return redirect(url_for('sales.entry'))

    product = Product.query.get_or_404(product_id)

    if product.current_stock < quantity_sold:
        flash(f'Cannot complete sale! Current stock for "{product.name}" is only {product.current_stock}. Requested: {quantity_sold}.', 'danger')
        return redirect(url_for('sales.entry'))

    try:
        sale_date = datetime.strptime(sale_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format. Use YYYY-MM-DD.', 'danger')
        return redirect(url_for('sales.entry'))

    total_price = float(product.price) * quantity_sold

    # Record sale
    sale = Sale(
        product_id=product.id,
        quantity_sold=quantity_sold,
        total_price=total_price,
        sale_date=sale_date
    )
    db.session.add(sale)

    # Automatically reduce current stock
    was_low_stock = product.is_low_stock
    product.current_stock -= quantity_sold
    
    check_and_send_low_stock_alert(product, was_low_stock)

    # Record inventory transaction
    tx = InventoryTransaction(
        product_id=product.id,
        transaction_type='Stock Out',
        quantity=-quantity_sold,
        notes=f'Sale transaction #{sale_date_str} - Sold {quantity_sold} units'
    )
    db.session.add(tx)

    try:
        db.session.commit()
        # Retrain AI forecast for this product
        train_and_forecast_product(db.session, product.id)
        flash(f'Sale recorded successfully! Total: ₹{total_price:,.2f}. Stock updated for "{product.name}".', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error recording sale: {str(e)}', 'danger')

    return redirect(url_for('sales.history'))

@sales_bp.route('/download-template')
@login_required
def download_template():
    """Serve the sample CSV template for historical sales batch import."""
    from flask import Response
    template_path = os.path.join(current_app.root_path, 'dataset', 'sample_upload_format.csv')
    if os.path.exists(template_path):
        with open(template_path, 'r', encoding='utf-8') as f:
            csv_data = f.read()
    else:
        csv_data = (
            "product_id_str,sale_date,quantity_sold\n"
            "PRD-2001,2026-04-01,15\n"
            "PRD-2001,2026-04-02,18\n"
            "PRD-2001,2026-04-03,12\n"
            "PRD-2003,2026-04-01,5\n"
            "PRD-2003,2026-04-02,8\n"
            "PRD-2006,2026-04-01,40\n"
            "PRD-2009,2026-04-01,10\n"
            "PRD-2014,2026-04-01,3\n"
        )
    
    if not csv_data.startswith('\ufeff'):
        csv_data = '\ufeff' + csv_data

    response = Response(csv_data, mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=sample_upload_format.csv'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

@sales_bp.route('/upload-csv', methods=['GET', 'POST'])
@login_required
def upload_csv():
    if request.method == 'POST':
        # ── Guard: file presence ──────────────────────────────────────
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file part in the request.'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected for upload.'}), 400

        if not file.filename.lower().endswith('.csv'):
            return jsonify({'success': False, 'error': 'Invalid file format. Only .csv files are accepted.'}), 400

        # ── Save uploaded file ────────────────────────────────────────
        filename = secure_filename(file.filename)
        upload_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)

        try:
            file.save(upload_path)
        except Exception as e:
            return jsonify({'success': False, 'error': f'Failed to save uploaded file: {str(e)}'}), 500

        # ── Read CSV with BOM support and detect headers ──────────────
        try:
            sample_df = pd.read_csv(upload_path, nrows=5, encoding='utf-8-sig', dtype=str)
        except Exception as e:
            return jsonify({'success': False, 'error': f'Cannot parse CSV file: {str(e)}'}), 400

        raw_columns = [str(c).strip() for c in sample_df.columns]
        
        # Build normalized column header alias mapping
        col_map = {}
        for col in raw_columns:
            clean_col = col.lower().replace(' ', '_').replace('-', '_').replace('\ufeff', '')
            if clean_col in ('product_id_str', 'product_id', 'product_code', 'product', 'item_id', 'productid', 'productcode', 'sku') and 'product_id_str' not in col_map:
                col_map['product_id_str'] = col
            elif clean_col in ('sale_date', 'date', 'transaction_date', 'sales_date', 'saledate', 'order_date') and 'sale_date' not in col_map:
                col_map['sale_date'] = col
            elif clean_col in ('quantity_sold', 'quantity', 'qty', 'qty_sold', 'units_sold', 'quantitysold', 'units', 'count') and 'quantity_sold' not in col_map:
                col_map['quantity_sold'] = col

        required_keys = ['product_id_str', 'sale_date', 'quantity_sold']
        missing_keys = [k for k in required_keys if k not in col_map]
        if missing_keys:
            return jsonify({
                'success': False,
                'error': f'Could not find required columns in your CSV: {", ".join(missing_keys)}. '
                         f'Found columns: {", ".join(raw_columns)}. '
                         f'Accepted column names are: product_id_str (or product_id), sale_date (or date), quantity_sold (or quantity).'
            }), 400

        col_pid = col_map['product_id_str']
        col_date = col_map['sale_date']
        col_qty = col_map['quantity_sold']

        # ── Pre-load all products with multi-identifier lookup ────────
        try:
            all_products = Product.query.all()
        except Exception as e:
            return jsonify({'success': False, 'error': f'Database error loading products: {str(e)}'}), 500

        product_lookup = {}  # key -> (id, price, name, canonical_pid)
        for p in all_products:
            val_tuple = (p.id, float(p.price) if p.price else 0.0, p.name, p.product_id_str)
            # 1. Exact canonical string (e.g. PRD-1001)
            product_lookup[p.product_id_str] = val_tuple
            # 2. Lowercase (e.g. prd-1001)
            product_lookup[p.product_id_str.lower()] = val_tuple
            # 3. Without hyphens (e.g. PRD1001, prd1001)
            product_lookup[p.product_id_str.replace('-', '')] = val_tuple
            product_lookup[p.product_id_str.replace('-', '').lower()] = val_tuple
            # 4. Integer database ID as string (e.g. "1")
            product_lookup[str(p.id)] = val_tuple
            # 5. Product name (lowercase)
            if p.name:
                product_lookup[p.name.strip().lower()] = val_tuple
            # 6. SKU (if available)
            if p.sku:
                product_lookup[p.sku.strip()] = val_tuple
                product_lookup[p.sku.strip().lower()] = val_tuple

        # Sample valid products to show in user guidance
        sample_valid_pids = [f"{p.product_id_str} ({p.name})" for p in all_products[:8]]

        # ── Helper for flexible date parsing ──────────────────────────
        def parse_date_val(d_raw):
            if not d_raw or pd.isna(d_raw):
                return None
            s = str(d_raw).strip()
            for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y%m%d', '%Y-%m-%d %H:%M:%S'):
                try:
                    return datetime.strptime(s, fmt).date()
                except ValueError:
                    continue
            return None

        # ── Helper for quantity parsing ───────────────────────────────
        def parse_qty_val(q_raw):
            if q_raw is None or pd.isna(q_raw):
                return None
            try:
                val = int(float(str(q_raw).strip().replace(',', '')))
                return val if val >= 0 else None
            except (ValueError, TypeError):
                return None

        # ── Tracking counters & error details ─────────────────────────
        total_rows = 0
        inserted_count = 0
        missing_value_rows = 0
        csv_duplicate_rows = 0
        db_duplicate_rows = 0
        invalid_product_rows = 0
        invalid_date_rows = 0
        invalid_quantity_rows = 0
        invalid_product_ids_found = set()
        affected_product_ids = set()
        rejection_details = []  # Detailed list of up to 25 rejected rows

        seen_in_file = set()

        # ── Pre-load existing sales for bulk duplicate detection ──────
        existing_sales_set = set()
        try:
            existing_rows = db.session.query(Sale.product_id, Sale.sale_date, Sale.quantity_sold).all()
            for pid, sdate, qty in existing_rows:
                existing_sales_set.add((pid, str(sdate), qty))
        except Exception as e:
            current_app.logger.warning(f'Could not pre-load existing sales: {e}')

        # ── Process CSV in chunks ─────────────────────────────────────
        CHUNK_SIZE = 2000
        INSERT_BATCH_SIZE = 500
        records_to_insert = []
        row_idx = 1  # 1-based data row counter (header is row 1 in Excel)

        try:
            for chunk in pd.read_csv(upload_path, chunksize=CHUNK_SIZE, dtype=str, encoding='utf-8-sig'):
                for _, row in chunk.iterrows():
                    row_idx += 1
                    total_rows += 1

                    raw_pid = row.get(col_pid)
                    raw_date = row.get(col_date)
                    raw_qty = row.get(col_qty)

                    # 1. Missing values check
                    if pd.isna(raw_pid) or pd.isna(raw_date) or pd.isna(raw_qty) or str(raw_pid).strip() == '' or str(raw_date).strip() == '':
                        missing_value_rows += 1
                        if len(rejection_details) < 25:
                            rejection_details.append({
                                'row': row_idx,
                                'field': 'missing_fields',
                                'value': f"pid={raw_pid}, date={raw_date}, qty={raw_qty}",
                                'reason': 'Missing one or more required fields.'
                            })
                        continue

                    p_clean = str(raw_pid).strip()
                    s_date_str = str(raw_date).strip()
                    qty_str = str(raw_qty).strip()

                    # 2. Product ID resolution
                    p_info = product_lookup.get(p_clean) or product_lookup.get(p_clean.lower())
                    if not p_info:
                        invalid_product_rows += 1
                        invalid_product_ids_found.add(p_clean)
                        if len(rejection_details) < 25:
                            rejection_details.append({
                                'row': row_idx,
                                'field': 'product_id',
                                'value': p_clean,
                                'reason': f"Product identifier '{p_clean}' was not found in inventory catalog."
                            })
                        continue

                    prod_id, prod_price, prod_name, canonical_pid = p_info

                    # 3. Date validation
                    s_date = parse_date_val(s_date_str)
                    if not s_date:
                        invalid_date_rows += 1
                        if len(rejection_details) < 25:
                            rejection_details.append({
                                'row': row_idx,
                                'field': 'sale_date',
                                'value': s_date_str,
                                'reason': f"Invalid date format '{s_date_str}' (expected YYYY-MM-DD)."
                            })
                        continue

                    # 4. Quantity validation
                    qty = parse_qty_val(qty_str)
                    if qty is None:
                        invalid_quantity_rows += 1
                        if len(rejection_details) < 25:
                            rejection_details.append({
                                'row': row_idx,
                                'field': 'quantity_sold',
                                'value': qty_str,
                                'reason': f"Invalid quantity '{qty_str}' (must be a positive integer)."
                            })
                        continue

                    # 5. In-file duplicate check
                    file_key = (prod_id, str(s_date), qty)
                    if file_key in seen_in_file:
                        csv_duplicate_rows += 1
                        continue
                    seen_in_file.add(file_key)

                    # 6. Database duplicate check
                    if file_key in existing_sales_set:
                        db_duplicate_rows += 1
                        continue

                    # 7. Valid record -> queue for bulk insert
                    total_price = prod_price * qty
                    records_to_insert.append({
                        'product_id': prod_id,
                        'quantity_sold': qty,
                        'total_price': total_price,
                        'sale_date': s_date,
                    })
                    existing_sales_set.add(file_key)
                    affected_product_ids.add(prod_id)

                    if len(records_to_insert) >= INSERT_BATCH_SIZE:
                        db.session.bulk_insert_mappings(Sale, records_to_insert)
                        inserted_count += len(records_to_insert)
                        records_to_insert = []

            # Insert remaining records
            if records_to_insert:
                db.session.bulk_insert_mappings(Sale, records_to_insert)
                inserted_count += len(records_to_insert)
                records_to_insert = []

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'CSV import database error: {e}')
            return jsonify({
                'success': False,
                'error': f'Database error during import: {str(e)}',
                'summary': {
                    'total_rows': total_rows,
                    'inserted': inserted_count,
                    'skipped': total_rows - inserted_count
                }
            }), 500

        # Cleanup uploaded file
        try:
            os.remove(upload_path)
        except OSError:
            pass

        skipped_total = (missing_value_rows + csv_duplicate_rows + db_duplicate_rows +
                         invalid_product_rows + invalid_date_rows + invalid_quantity_rows)

        result = {
            'success': True,
            'summary': {
                'total_rows': total_rows,
                'inserted': inserted_count,
                'skipped': skipped_total,
                'missing_values': missing_value_rows,
                'csv_duplicates': csv_duplicate_rows,
                'db_duplicates': db_duplicate_rows,
                'invalid_product_ids': invalid_product_rows,
                'invalid_dates': invalid_date_rows,
                'invalid_quantities': invalid_quantity_rows,
                'affected_products': len(affected_product_ids),
            },
            'rejection_details': rejection_details,
            'sample_valid_pids': sample_valid_pids
        }

        if invalid_product_ids_found:
            result['invalid_product_id_samples'] = sorted(invalid_product_ids_found)[:20]

        return jsonify(result), 200

    # ── GET request — render the upload page ──────────────────────────
    return render_template('sales/csv_upload.html')


# ─────────────────────────────────────────────────────────
# NEW: Sales Analytics API Endpoints
# ─────────────────────────────────────────────────────────

def _parse_date_filters(args):
    """Parse date preset or custom date range from request args. Returns (start_date, end_date) or (None, None)."""
    today = get_latest_sale_date()
    preset = args.get('date_preset', '').strip().lower()
    
    if preset == 'today':
        return today, today
    elif preset == 'yesterday':
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    elif preset == 'last7':
        return today - timedelta(days=6), today
    elif preset == 'last30':
        return today - timedelta(days=29), today
    elif preset == 'this_month':
        return today.replace(day=1), today
    elif preset == 'last_month':
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        first_of_prev_month = last_of_prev_month.replace(day=1)
        return first_of_prev_month, last_of_prev_month
    elif preset == 'this_year':
        return today.replace(month=1, day=1), today
    
    # Custom date range
    date_from_str = args.get('date_from', '').strip()
    date_to_str = args.get('date_to', '').strip()
    start_date = None
    end_date = None
    
    if date_from_str:
        try:
            start_date = datetime.strptime(date_from_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    if date_to_str:
        try:
            end_date = datetime.strptime(date_to_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    return start_date, end_date


def _build_filtered_query(args):
    """Build a filtered Sale query from request args. Returns the query object."""
    query = db.session.query(Sale).join(Product, Sale.product_id == Product.id)
    
    # Date filters
    start_date, end_date = _parse_date_filters(args)
    if start_date:
        query = query.filter(Sale.sale_date >= start_date)
    if end_date:
        query = query.filter(Sale.sale_date <= end_date)
    
    # Product type filter
    product_type = args.get('product_type', '').strip()
    if product_type and product_type.lower() not in ('all', ''):
        query = query.filter(Product.product_type == product_type)
    
    # Category filter
    category = args.get('category', '').strip()
    if category and category.lower() not in ('all', ''):
        query = query.filter(Product.category == category)
    
    # Brand filter
    brand = args.get('brand', '').strip()
    if brand and brand.lower() not in ('all', ''):
        query = query.filter(Product.brand == brand)
    
    # Product name filter
    product_name = args.get('product_name', '').strip()
    if product_name and product_name.lower() not in ('all', ''):
        query = query.filter(Product.name.ilike(f'%{product_name}%'))
    
    # Amount range filters
    min_amount = args.get('min_amount', '').strip()
    if min_amount:
        try:
            query = query.filter(Sale.total_price >= float(min_amount))
        except ValueError:
            pass
    
    max_amount = args.get('max_amount', '').strip()
    if max_amount:
        try:
            query = query.filter(Sale.total_price <= float(max_amount))
        except ValueError:
            pass
    
    # Universal search (Sale ID, Product ID, Product Name, Brand)
    search = args.get('search', '').strip()
    if search:
        search_term = f'%{search}%'
        # Try to parse as integer for Sale ID matching
        try:
            sale_id_val = int(search)
            query = query.filter(
                db.or_(
                    Sale.id == sale_id_val,
                    Product.product_id_str.ilike(search_term),
                    Product.name.ilike(search_term),
                    Product.brand.ilike(search_term)
                )
            )
        except ValueError:
            query = query.filter(
                db.or_(
                    Product.product_id_str.ilike(search_term),
                    Product.name.ilike(search_term),
                    Product.brand.ilike(search_term)
                )
            )
    
    return query


@sales_bp.route('/api/data')
@login_required
def api_data():
    """Return filtered, sorted, paginated sales data."""
    query = _build_filtered_query(request.args)
    
    # Get total count before pagination
    total_count = query.count()
    
    # Sorting
    sort_by = request.args.get('sort_by', 'sale_date').strip()
    sort_dir = request.args.get('sort_dir', 'desc').strip().lower()
    
    sort_map = {
        'id': Sale.id,
        'sale_date': Sale.sale_date,
        'amount': Sale.total_price,
        'quantity': Sale.quantity_sold,
        'product': Product.name,
        'brand': Product.brand,
    }
    
    sort_column = sort_map.get(sort_by, Sale.sale_date)
    if sort_dir == 'asc':
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))
    
    # Secondary sort for stability
    if sort_by != 'id':
        query = query.order_by(desc(Sale.id))
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    per_page = min(per_page, 100)  # Cap at 100
    
    offset = (page - 1) * per_page
    sales = query.offset(offset).limit(per_page).all()
    
    total_pages = (total_count + per_page - 1) // per_page if per_page > 0 else 1
    
    data = []
    for s in sales:
        p = s.product
        data.append({
            'id': s.id,
            'sale_date': s.sale_date.strftime('%Y-%m-%d') if s.sale_date else '',
            'product_name': p.name if p else 'N/A',
            'product_id_str': p.product_id_str if p else '',
            'product_type': p.product_type if p else '',
            'category': p.category if p else '',
            'brand': p.brand if p else '',
            'quantity_sold': s.quantity_sold,
            'total_price': float(s.total_price) if s.total_price else 0
        })
    
    return jsonify({
        'data': data,
        'total_count': total_count,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@sales_bp.route('/api/summary')
@login_required
def api_summary():
    """Return KPI summary cards based on filters."""
    query = _build_filtered_query(request.args)
    sales_list = query.all()
    
    today = get_latest_sale_date()
    
    # Filtered metrics
    total_revenue = sum(float(s.total_price) for s in sales_list if s.total_price)
    total_orders = len(sales_list)
    total_units = sum(s.quantity_sold for s in sales_list if s.quantity_sold)
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
    
    # Today-specific metrics (always from today regardless of filters)
    today_sales = [s for s in sales_list if s.sale_date == today]
    today_revenue = sum(float(s.total_price) for s in today_sales if s.total_price)
    today_orders = len(today_sales)
    today_units = sum(s.quantity_sold for s in today_sales if s.quantity_sold)
    
    # Monthly revenue (current month from filtered data)
    first_of_month = today.replace(day=1)
    month_sales = [s for s in sales_list if s.sale_date and s.sale_date >= first_of_month]
    monthly_revenue = sum(float(s.total_price) for s in month_sales if s.total_price)
    
    # Top selling product (by quantity in filtered set)
    product_qty = {}
    product_rev = {}
    brand_qty = {}
    for s in sales_list:
        if s.product:
            pname = s.product.name
            bname = s.product.brand
            product_qty[pname] = product_qty.get(pname, 0) + (s.quantity_sold or 0)
            product_rev[pname] = product_rev.get(pname, 0) + float(s.total_price or 0)
            brand_qty[bname] = brand_qty.get(bname, 0) + (s.quantity_sold or 0)
    
    top_product = max(product_qty, key=product_qty.get) if product_qty else 'N/A'
    top_brand = max(brand_qty, key=brand_qty.get) if brand_qty else 'N/A'
    
    return jsonify({
        'today_revenue': round(today_revenue, 2),
        'today_orders': today_orders,
        'today_units': today_units,
        'total_revenue': round(total_revenue, 2),
        'total_orders': total_orders,
        'total_units': total_units,
        'avg_order_value': round(avg_order_value, 2),
        'top_product': top_product,
        'top_brand': top_brand,
        'monthly_revenue': round(monthly_revenue, 2)
    })


@sales_bp.route('/api/charts')
@login_required
def api_charts():
    """Return chart datasets based on current filters."""
    query = _build_filtered_query(request.args)
    sales_list = query.all()
    
    # 1. Daily Revenue Trend (last 30 data points)
    daily_data = {}
    for s in sales_list:
        if s.sale_date:
            day_str = s.sale_date.strftime('%Y-%m-%d')
            daily_data[day_str] = daily_data.get(day_str, 0) + float(s.total_price or 0)
    
    sorted_days = sorted(daily_data.keys())[-30:]  # Last 30 days with data
    daily_chart = {
        'labels': sorted_days,
        'values': [round(daily_data[d], 2) for d in sorted_days]
    }
    
    # 2. Daily Units Sold
    daily_units = {}
    for s in sales_list:
        if s.sale_date:
            day_str = s.sale_date.strftime('%Y-%m-%d')
            daily_units[day_str] = daily_units.get(day_str, 0) + (s.quantity_sold or 0)
    
    daily_units_chart = {
        'labels': sorted_days,
        'values': [daily_units.get(d, 0) for d in sorted_days]
    }
    
    # 3. Monthly Revenue
    monthly_data = {}
    for s in sales_list:
        if s.sale_date:
            month_key = s.sale_date.strftime('%Y-%m')
            monthly_data[month_key] = monthly_data.get(month_key, 0) + float(s.total_price or 0)
    
    sorted_months = sorted(monthly_data.keys())[-12:]  # Last 12 months
    monthly_chart = {
        'labels': sorted_months,
        'values': [round(monthly_data[m], 2) for m in sorted_months]
    }
    
    # 4. Brand Performance
    brand_data = {}
    for s in sales_list:
        if s.product:
            brand = s.product.brand
            brand_data[brand] = brand_data.get(brand, 0) + float(s.total_price or 0)
    
    # Sort by revenue desc and take top 10
    sorted_brands = sorted(brand_data.items(), key=lambda x: x[1], reverse=True)[:10]
    brand_chart = {
        'labels': [b[0] for b in sorted_brands],
        'values': [round(b[1], 2) for b in sorted_brands]
    }
    
    # 5. Category Performance
    category_data = {}
    for s in sales_list:
        if s.product:
            cat = s.product.category
            category_data[cat] = category_data.get(cat, 0) + float(s.total_price or 0)
    
    sorted_cats = sorted(category_data.items(), key=lambda x: x[1], reverse=True)[:10]
    category_chart = {
        'labels': [c[0] for c in sorted_cats],
        'values': [round(c[1], 2) for c in sorted_cats]
    }
    
    # 6. Top Selling Products (by units)
    product_data = {}
    for s in sales_list:
        if s.product:
            pname = s.product.name
            product_data[pname] = product_data.get(pname, 0) + (s.quantity_sold or 0)
    
    sorted_products = sorted(product_data.items(), key=lambda x: x[1], reverse=True)[:10]
    top_products_chart = {
        'labels': [p[0][:30] for p in sorted_products],  # Truncate long names
        'values': [p[1] for p in sorted_products]
    }
    
    return jsonify({
        'daily_revenue': daily_chart,
        'daily_units': daily_units_chart,
        'monthly_revenue': monthly_chart,
        'brand_performance': brand_chart,
        'category_performance': category_chart,
        'top_products': top_products_chart
    })


@sales_bp.route('/api/export')
@login_required
def api_export():
    """Return full filtered dataset (no pagination) for export."""
    query = _build_filtered_query(request.args)
    query = query.order_by(desc(Sale.sale_date), desc(Sale.id))
    sales_list = query.all()
    
    data = []
    for s in sales_list:
        p = s.product
        data.append({
            'id': s.id,
            'sale_date': s.sale_date.strftime('%Y-%m-%d') if s.sale_date else '',
            'product_id_str': p.product_id_str if p else '',
            'product_name': p.name if p else 'N/A',
            'product_type': p.product_type if p else '',
            'category': p.category if p else '',
            'brand': p.brand if p else '',
            'quantity_sold': s.quantity_sold,
            'total_price': float(s.total_price) if s.total_price else 0
        })
    
    return jsonify({'data': data, 'total_count': len(data)})
