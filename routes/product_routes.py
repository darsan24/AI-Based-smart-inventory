from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from models import db, Product, InventoryTransaction
from routes.auth_routes import login_required

product_bp = Blueprint('products', __name__, url_prefix='/products')

@product_bp.route('/api/product_types')
@login_required
def product_types():
    types = db.session.query(Product.product_type).distinct().order_by(Product.product_type.asc()).all()
    type_list = [t[0] for t in types if t[0]]
    return jsonify({'product_types': type_list})

@product_bp.route('/api/brands_by_category')
@login_required
def brands_by_category():
    category = request.args.get('category', '').strip()
    product_type = request.args.get('product_type', '').strip()
    
    query = db.session.query(Product.brand)
    
    if product_type and product_type.lower() not in ['all', 'all types', 'all product types', 'all_types']:
        query = query.filter(Product.product_type == product_type)
        
    if category and category.lower() not in ['all', 'all categories', 'all_categories']:
        query = query.filter(Product.category == category)
        
    brands = query.distinct().order_by(Product.brand.asc()).all()
    
    brand_list = [b[0] for b in brands if b[0]]
    return jsonify({'brands': brand_list})

@product_bp.route('/api/categories_by_product_type')
@login_required
def categories_by_product_type():
    product_type = request.args.get('product_type', '').strip()
    brand = request.args.get('brand', '').strip()
    
    query = db.session.query(Product.category)
    if product_type and product_type.lower() not in ['all', 'all product types', 'all_types', 'all types']:
        query = query.filter(Product.product_type == product_type)
    if brand and brand.lower() not in ['all', 'all brands', 'all_brands']:
        query = query.filter(Product.brand == brand)
    
    categories = query.distinct().order_by(Product.category.asc()).all()
    cat_list = [c[0] for c in categories if c[0]]
    return jsonify({'categories': cat_list})

@product_bp.route('/')
@login_required
def list_products():
    search_query = request.args.get('search', '').strip()
    product_type_filter = request.args.get('product_type', '').strip()
    category_filter = request.args.get('category', '').strip()
    brand_filter = request.args.get('brand', '').strip()
    abc_filter = request.args.get('abc_class', '').strip().upper()
    xyz_filter = request.args.get('xyz_class', '').strip().upper()
    combined_filter = request.args.get('combined_class', '').strip().upper()
    sort_by = request.args.get('sort', 'id').strip()

    query = Product.query

    if search_query:
        query = query.filter(
            (Product.name.ilike(f'%{search_query}%')) |
            (Product.product_id_str.ilike(f'%{search_query}%')) |
            (Product.product_type.ilike(f'%{search_query}%')) |
            (Product.brand.ilike(f'%{search_query}%')) |
            (Product.category.ilike(f'%{search_query}%')) |
            (Product.supplier_name.ilike(f'%{search_query}%'))
        )

    if product_type_filter and product_type_filter != 'All':
        query = query.filter_by(product_type=product_type_filter)
        
    if category_filter and category_filter != 'All':
        query = query.filter_by(category=category_filter)
        
    if brand_filter and brand_filter != 'All':
        query = query.filter_by(brand=brand_filter)

    if abc_filter and abc_filter in ('A', 'B', 'C'):
        query = query.filter_by(abc_class=abc_filter)

    if xyz_filter and xyz_filter in ('X', 'Y', 'Z'):
        query = query.filter_by(xyz_class=xyz_filter)

    if combined_filter and len(combined_filter) == 2:
        query = query.filter_by(abc_class=combined_filter[0], xyz_class=combined_filter[1])

    # Sorting
    if sort_by == 'revenue':
        query = query.order_by(Product.revenue_contribution_percent.desc().nullslast())
    elif sort_by == 'variability':
        query = query.order_by(Product.demand_variability.asc().nullslast())
    elif sort_by == 'name':
        query = query.order_by(Product.name.asc())
    elif sort_by == 'stock':
        query = query.order_by(Product.current_stock.asc())
    elif sort_by == 'abc':
        query = query.order_by(Product.abc_class.asc().nullslast(), Product.xyz_class.asc().nullslast())
    else:
        query = query.order_by(db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc())

    products = query.all()

    # Get distinct product types for filter dropdown
    all_product_types = db.session.query(Product.product_type).distinct().order_by(Product.product_type.asc()).all()
    product_types = [p[0] for p in all_product_types if p[0]]
    
    # Dynamically fetch categories and brands from database based on selected filters
    cat_q = db.session.query(Product.category).distinct()
    brand_q = db.session.query(Product.brand).distinct()

    if product_type_filter and product_type_filter != 'All':
        cat_q = cat_q.filter_by(product_type=product_type_filter)
        brand_q = brand_q.filter_by(product_type=product_type_filter)
    if brand_filter and brand_filter != 'All':
        cat_q = cat_q.filter_by(brand=brand_filter)
    if category_filter and category_filter != 'All':
        brand_q = brand_q.filter_by(category=category_filter)
        
    categories = [c[0] for c in cat_q.order_by(Product.category.asc()).all() if c[0]]
    brands = [b[0] for b in brand_q.order_by(Product.brand.asc()).all() if b[0]]

    # Generate comprehensive product_data_map required by template modals and JS
    all_products = Product.query.all()
    product_data_map = {}
    for p in all_products:
        if p.product_type not in product_data_map:
            product_data_map[p.product_type] = {
                'categories': set(),
                'brands': set(),
                'products': []
            }
        product_data_map[p.product_type]['categories'].add(p.category)
        product_data_map[p.product_type]['brands'].add(p.brand)
        product_data_map[p.product_type]['products'].append({
            'product_id': p.product_id_str,
            'name': p.name,
            'type': p.product_type,
            'category': p.category,
            'brand': p.brand,
            'price': float(p.price) if p.price else 0.0,
            'current_stock': p.current_stock,
            'reorder_level': p.reorder_level,
            'supplier': p.supplier_name
        })

    # Convert sets to lists for JSON serialization / Jinja iteration
    for p_type in product_data_map:
        product_data_map[p_type]['categories'] = list(product_data_map[p_type]['categories'])
        product_data_map[p_type]['brands'] = list(product_data_map[p_type]['brands'])

    return render_template(
        'products/index.html',
        products=products,
        product_types=product_types,
        categories=categories,
        brands=brands,
        product_data_map=product_data_map,
        search_query=search_query,
        selected_product_type=product_type_filter,
        selected_category=category_filter,
        selected_brand=brand_filter,
        selected_abc=abc_filter,
        selected_xyz=xyz_filter,
        selected_combined=combined_filter,
        sort_by=sort_by
    )

@product_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_product():
    if request.method == 'POST':
        product_id_str = request.form.get('product_id_str', '').strip().upper()
        product_type = request.form.get('product_type', '').strip()
        category = request.form.get('category', '').strip()
        brand = request.form.get('brand', '').strip()
        name = request.form.get('name', '').strip()
        price = request.form.get('price', '0.00')
        current_stock = request.form.get('current_stock', '0')
        reorder_level = request.form.get('reorder_level', '10')
        supplier_name = request.form.get('supplier_name', '').strip()
        description = request.form.get('description', '').strip()

        # Validation: Product Type, Category, and Brand are mandatory
        if not product_id_str or not product_type or not category or not brand or not name:
            flash('Product ID, Product Type, Category, Brand, and Product Name are required fields!', 'warning')
            return redirect(url_for('products.list_products'))

        existing_p = Product.query.filter_by(product_id_str=product_id_str).first()
        if existing_p:
            flash(f'Product ID "{product_id_str}" already exists!', 'danger')
            return redirect(url_for('products.list_products'))

        try:
            p = Product(
                # pyrefly: ignore [unexpected-keyword]
                product_id_str=product_id_str,
                # pyrefly: ignore [unexpected-keyword]
                product_type=product_type,
                # pyrefly: ignore [unexpected-keyword]
                name=name,
                # pyrefly: ignore [unexpected-keyword]
                category=category,
                # pyrefly: ignore [unexpected-keyword]
                brand=brand,
                # pyrefly: ignore [unexpected-keyword]
                price=float(price),
                # pyrefly: ignore [unexpected-keyword]
                current_stock=int(current_stock),
                # pyrefly: ignore [unexpected-keyword]
                reorder_level=int(reorder_level),
                # pyrefly: ignore [unexpected-keyword]
                supplier_name=supplier_name,
                # pyrefly: ignore [unexpected-keyword]
                description=description
            )
            db.session.add(p)
            db.session.commit()

            # Record initial stock transaction
            if int(current_stock) > 0:
                tx = InventoryTransaction(
                    # pyrefly: ignore [unexpected-keyword]
                    product_id=p.id,
                    # pyrefly: ignore [unexpected-keyword]
                    transaction_type='Stock In',
                    # pyrefly: ignore [unexpected-keyword]
                    quantity=int(current_stock),
                    # pyrefly: ignore [unexpected-keyword]
                    notes='Initial Stock Setup on Product Creation'
                )
                db.session.add(tx)
                db.session.commit()


            flash(f'Product "{name}" ({product_id_str}) created successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding product: {str(e)}', 'danger')

        return redirect(url_for('products.list_products'))

    return redirect(url_for('products.list_products'))

@product_bp.route('/edit/<int:id>', methods=['POST'])
@login_required
def edit_product(id):
    product = Product.query.get_or_404(id)
    
    product_type = request.form.get('product_type', product.product_type).strip()
    category = request.form.get('category', product.category).strip()
    brand = request.form.get('brand', product.brand).strip()
    name = request.form.get('name', product.name).strip()

    if not product_type or not category or not brand or not name:
        flash('Product Type, Category, Brand, and Product Name cannot be empty!', 'warning')
        return redirect(url_for('products.list_products'))

    product.product_type = product_type
    product.category = category
    product.brand = brand
    product.name = name
    product.price = float(request.form.get('price', product.price))
    product.reorder_level = int(request.form.get('reorder_level', product.reorder_level))
    product.supplier_name = request.form.get('supplier_name', product.supplier_name).strip()
    product.description = request.form.get('description', product.description).strip()

    try:
        db.session.commit()

        flash(f'Product "{product.name}" updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating product: {str(e)}', 'danger')

    return redirect(url_for('products.list_products'))

@product_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    name = product.name
    try:
        db.session.delete(product)
        db.session.commit()
        flash(f'Product "{name}" deleted successfully!', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting product: {str(e)}', 'danger')

    return redirect(url_for('products.list_products'))

@product_bp.route('/<string:product_id>')
@login_required
def view_product_by_id(product_id):
    """Allows direct navigation to /products/PRD-XXXX by product ID."""
    return redirect(url_for('products.list_products', search=product_id))
