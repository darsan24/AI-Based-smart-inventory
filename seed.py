import os
import csv
from datetime import datetime
from app import create_app
from models import db, User, Product, InventoryTransaction, Sale
from ai.patchtst_model import train_and_forecast_product
from ai.reorder_engine import generate_reorder_recommendation
from ai.classification_engine import classify_all_products

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_CSV = os.path.join(BASE_DIR, 'data', 'products_real_clean.csv')
SALES_CSV = os.path.join(BASE_DIR, 'data', 'sales_real_clean.csv')


def seed_database():
    app = create_app()
    with app.app_context():
        print("[SEED] Ensuring database tables exist...")
        db.create_all()

        # 1. Seed Admin User ONLY if no user exists at all
        # If any user or admin exists: DO NOT recreate, DO NOT overwrite password, DO NOT regenerate hash.
        existing_user_count = User.query.count()
        if existing_user_count == 0:
            admin = User(
                username='admin',
                name='Admin User',
                email='admin@inventory.ai',
                role='admin',
                is_active=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("[SEED] Default admin user created (admin / admin123).")
        else:
            print(f"[SEED] Existing account(s) found ({existing_user_count} users). Keeping existing credentials and password hashes untouched.")

        # 2. Seed Real Products from products_real_clean.csv
        print(f"[SEED] Reading products from {PRODUCTS_CSV}...")
        if not os.path.exists(PRODUCTS_CSV):
            raise FileNotFoundError(f"Products CSV not found at {PRODUCTS_CSV}")

        products_to_add = []
        with open(PRODUCTS_CSV, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                product = Product(
                    product_id_str=row['product_id_str'].strip(),
                    product_type=row['product_type'].strip(),
                    name=row['name'].strip(),
                    category=row['category'].strip(),
                    brand=row['brand'].strip(),
                    price=float(row['price']),
                    cost_price=float(row['cost_price']),
                    mrp=float(row['mrp']),
                    currency=row.get('currency', 'INR').strip(),
                    current_stock=int(float(row['current_stock'])),
                    reorder_level=int(float(row['reorder_level'])),
                    safety_stock=int(float(row['safety_stock'])),
                    maximum_stock=int(float(row['maximum_stock'])),
                    unit=row.get('unit', 'Nos').strip(),
                    sku=row['sku'].strip(),
                    supplier_name=row.get('supplier_name', '').strip(),
                    description=row.get('description', '').strip()
                )
                products_to_add.append(product)

        db.session.add_all(products_to_add)
        db.session.commit()
        print(f"[SEED] Successfully seeded {len(products_to_add)} real products.")

        # Build lookup table: product_id_str -> database integer ID
        db_products = Product.query.all()
        product_map = {p.product_id_str: p.id for p in db_products}

        # 3. Seed Real Sales from sales_real_clean.csv in batches
        print(f"[SEED] Reading sales transactions from {SALES_CSV}...")
        if not os.path.exists(SALES_CSV):
            raise FileNotFoundError(f"Sales CSV not found at {SALES_CSV}")

        batch_size = 5000
        batch = []
        total_sales_count = 0
        now = datetime.utcnow()

        with open(SALES_CSV, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid_str = row['product_id_str'].strip()
                if pid_str not in product_map:
                    continue

                sale_data = {
                    'order_id': row.get('order_id', '').strip() or None,
                    'product_id': product_map[pid_str],
                    'quantity_sold': int(row['quantity_sold']),
                    'total_price': float(row['total_price_inr']),
                    'sale_date': datetime.strptime(row['sale_date'].strip(), '%Y-%m-%d').date(),
                    'created_at': now
                }
                batch.append(sale_data)

                if len(batch) >= batch_size:
                    db.session.bulk_insert_mappings(Sale, batch)
                    db.session.commit()
                    total_sales_count += len(batch)
                    batch = []
                    print(f"[SEED] ...inserted {total_sales_count} sales records...")

            if batch:
                db.session.bulk_insert_mappings(Sale, batch)
                db.session.commit()
                total_sales_count += len(batch)

        print(f"[SEED] Total sales records seeded: {total_sales_count}")

        # Note: InventoryTransaction is intentionally NOT populated with synthetic movements.
        # Leaving inventory_transactions table empty per strict project requirements.

        # 4. ABC / XYZ Inventory Classification
        print("[SEED] Running ABC/XYZ inventory classification...")
        class_summary = classify_all_products(db.session)
        print(f"[SEED] Classified {class_summary['total_products']} products:")
        print(f"       ABC: {class_summary['abc_counts']}")
        print(f"       XYZ: {class_summary['xyz_counts']}")
        print(f"       9-Box Matrix: {class_summary['matrix_9box']}")

        # 5. Trigger PatchTST Forecast Generation & Reorder Recommendations for all products
        print("[SEED] Running PatchTST Demand Forecast training & reorder recommendations for all products...")
        for p in db_products:
            print(f"[SEED] Forecasting product: {p.name} ({p.product_id_str})...")
            train_and_forecast_product(db.session, p.id)
            generate_reorder_recommendation(db.session, p.id)

        print("[SEED] Database seeding and AI forecasting completed successfully!")


if __name__ == '__main__':
    seed_database()
