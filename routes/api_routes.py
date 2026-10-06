from flask import Blueprint, request, jsonify
from models import db, Product
from routes.auth_routes import login_required

api_bp = Blueprint('api', __name__, url_prefix='/api')


def _clean_filter_param(val):
    if not val:
        return ''
    val = val.strip()
    if val.lower() in ('all', 'all types', 'all product types', 'all_types', 
                       'all categories', 'all_categories', 
                       'all brands', 'all_brands', 
                       'all products', 'all_products'):
        return ''
    return val


@api_bp.route('/filters/dependent', methods=['GET'])
@login_required
def get_dependent_filters():
    """
    Returns dynamically filtered dropdown values based on provided constraints.
    Supports full multi-directional dependency:
    - Brand -> Product Types, Categories, Products
    - Type -> Categories, Brands, Products
    - Category -> Product Types, Brands, Products
    - Product -> Type, Category, Brand
    """
    raw_type = request.args.get('product_type', '')
    raw_cat = request.args.get('category', '')
    raw_brand = request.args.get('brand', '')
    raw_pid = request.args.get('product_id', '') or request.args.get('product_id_str', '')
    trigger = request.args.get('trigger', '').strip().lower()

    product_type = _clean_filter_param(raw_type)
    category = _clean_filter_param(raw_cat)
    brand = _clean_filter_param(raw_brand)

    # Master distinct lists across whole database
    all_types = [r[0] for r in db.session.query(Product.product_type).distinct().order_by(Product.product_type.asc()).all() if r[0]]
    all_categories = [r[0] for r in db.session.query(Product.category).distinct().order_by(Product.category.asc()).all() if r[0]]
    all_brands = [r[0] for r in db.session.query(Product.brand).distinct().order_by(Product.brand.asc()).all() if r[0]]

    inferred = {}

    # 1. Product ID direct lookup
    if raw_pid and raw_pid.strip():
        pid_clean = raw_pid.strip()
        prod_obj = Product.query.filter(
            (Product.product_id_str == pid_clean) | 
            (Product.id == int(pid_clean) if pid_clean.isdigit() else False)
        ).first()
        if prod_obj:
            product_type = prod_obj.product_type
            category = prod_obj.category
            brand = prod_obj.brand
            inferred['product_type'] = prod_obj.product_type
            inferred['category'] = prod_obj.category
            inferred['brand'] = prod_obj.brand
            inferred['product_id'] = prod_obj.id
            inferred['product_id_str'] = prod_obj.product_id_str
            inferred['product_name'] = prod_obj.name

    # 2. If Category is selected and Type is not (or Category changed), infer Type
    if category:
        cat_types = [r[0] for r in db.session.query(Product.product_type).filter(Product.category == category).distinct().all() if r[0]]
        if len(cat_types) == 1:
            product_type = cat_types[0]
            inferred['product_type'] = cat_types[0]
        elif product_type and product_type not in cat_types:
            product_type = cat_types[0] if cat_types else ''
            inferred['product_type'] = product_type

    # 3. If Brand is selected, infer or constrain Type
    if brand:
        brand_types = [r[0] for r in db.session.query(Product.product_type).filter(Product.brand == brand).distinct().order_by(Product.product_type.asc()).all() if r[0]]
        if len(brand_types) == 1:
            product_type = brand_types[0]
            inferred['product_type'] = brand_types[0]
        elif product_type and product_type not in brand_types:
            # Current product_type is invalid for this brand -> clear it, do not guess
            product_type = ''

    # 4. Multi-directional queries for valid options
    # Types: filtered by brand and category if given
    type_query = db.session.query(Product.product_type).distinct()
    if brand:
        type_query = type_query.filter(Product.brand == brand)
    if category:
        type_query = type_query.filter(Product.category == category)
    product_types = [r[0] for r in type_query.order_by(Product.product_type.asc()).all() if r[0]]

    # Categories: filtered by product_type and brand if given
    cat_query = db.session.query(Product.category).distinct()
    if product_type:
        cat_query = cat_query.filter(Product.product_type == product_type)
    if brand:
        cat_query = cat_query.filter(Product.brand == brand)
    categories = [r[0] for r in cat_query.order_by(Product.category.asc()).all() if r[0]]

    # If only 1 category exists for the selected brand/type, infer it
    if len(categories) == 1 and (brand or product_type):
        inferred['category'] = categories[0]

    # Brands: filtered by product_type and category if given
    brand_query = db.session.query(Product.brand).distinct()
    if product_type:
        brand_query = brand_query.filter(Product.product_type == product_type)
    if category:
        brand_query = brand_query.filter(Product.category == category)
    brands = [r[0] for r in brand_query.order_by(Product.brand.asc()).all() if r[0]]

    if len(brands) == 1 and (product_type or category):
        inferred['brand'] = brands[0]

    # Products list
    prod_query = Product.query
    if product_type:
        prod_query = prod_query.filter(Product.product_type == product_type)
    if category:
        prod_query = prod_query.filter(Product.category == category)
    if brand:
        prod_query = prod_query.filter(Product.brand == brand)

    matched_products = prod_query.order_by(Product.name.asc()).all()
    product_names = [p.name for p in matched_products]
    products_list = [{
        'id': p.id,
        'product_id_str': p.product_id_str,
        'name': p.name,
        'product_type': p.product_type,
        'category': p.category,
        'brand': p.brand,
        'price': float(p.price) if p.price else 0.0,
        'current_stock': p.current_stock,
        'reorder_level': p.reorder_level,
        'sku': p.sku or '',
        'unit': p.unit or 'Nos'
    } for p in matched_products]

    return jsonify({
        'product_types': product_types,
        'categories': categories,
        'brands': brands,
        'product_names': product_names,
        'products': products_list,
        'all_product_types': all_types,
        'all_categories': all_categories,
        'all_brands': all_brands,
        'inferred': inferred,
        'selected': {
            'product_type': product_type,
            'category': category,
            'brand': brand
        }
    })

