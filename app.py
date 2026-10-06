import os
import socket
import logging
from flask import Flask, render_template, session
from config import Config
from models import db, Product, User

# Configure detailed logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def find_available_port(start_port=5000, max_attempts=10):
    """Finds an open port starting from start_port if occupied."""
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            res = sock.connect_ex(('127.0.0.1', p))
            if res != 0: # Port is available
                return p
    return start_port

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions safely
    try:
        db.init_app(app)
    except Exception as e:
        app.logger.error(f"Database initialization warning: {e}")

    # Register Blueprints
    from routes.auth_routes import auth_bp
    from routes.dashboard_routes import dashboard_bp
    from routes.product_routes import product_bp
    from routes.inventory_routes import inventory_bp
    from routes.sales_routes import sales_bp
    from routes.forecast_routes import forecast_bp
    from routes.report_routes import report_bp
    from routes.notification_routes import notification_bp
    from routes.api_routes import api_bp


    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(product_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(forecast_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(notification_bp)
    app.register_blueprint(api_bp)


    # Global context processor for sidebar navigation (low stock badge count)
    @app.context_processor
    def inject_global_data():
        low_stock_badge_count = 0
        if 'user_id' in session:
            try:
                low_stock_badge_count = Product.query.filter(Product.current_stock <= Product.reorder_level).count()
            except Exception:
                low_stock_badge_count = 0
        return dict(
            global_low_stock_count=low_stock_badge_count,
            global_theme='light'
        )

    # Error Handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('base.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return "Internal Server Error", 500

    # Create tables automatically with safe exception handler & column migration
    with app.app_context():
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        try:
            db.create_all()
            # Safe column migration for users.name if on existing SQLite/MySQL
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE users ADD COLUMN name VARCHAR(120) DEFAULT 'Admin User'"))
                    conn.commit()
            except Exception:
                pass
            # Safe column migration for users.is_active if on existing SQLite/MySQL
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
                    conn.commit()
            except Exception:
                pass
            # Safe column migration for forecast explanation fields
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE forecast_predictions ADD COLUMN explanation_summary TEXT"))
                    conn.commit()
            except Exception:
                pass
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE forecast_predictions ADD COLUMN top_factors TEXT"))
                    conn.commit()
            except Exception:
                pass
            # Safe column migration for baseline comparison fields
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE forecast_predictions ADD COLUMN baseline_predicted_demand NUMERIC(10, 2)"))
                    conn.commit()
            except Exception:
                pass
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE forecast_predictions ADD COLUMN baseline_method VARCHAR(50)"))
                    conn.commit()
            except Exception:
                pass
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE forecast_predictions ADD COLUMN baseline_mae NUMERIC(10, 4)"))
                    conn.commit()
            except Exception:
                pass
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE forecast_predictions ADD COLUMN baseline_rmse NUMERIC(10, 4)"))
                    conn.commit()
            except Exception:
                pass
            # Safe column migration for product ABC/XYZ classification fields
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE products ADD COLUMN abc_class VARCHAR(1)"))
                    conn.commit()
            except Exception:
                pass
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE products ADD COLUMN xyz_class VARCHAR(1)"))
                    conn.commit()
            except Exception:
                pass
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE products ADD COLUMN revenue_contribution_percent NUMERIC(5, 2)"))
                    conn.commit()
            except Exception:
                pass
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE products ADD COLUMN demand_variability NUMERIC(6, 4)"))
                    conn.commit()
            except Exception:
                pass
            try:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE products ADD COLUMN classification_updated_at DATETIME"))
                    conn.commit()
            except Exception:
                pass

            # Ensure default administrator exists ONLY IF no users exist.
            # Never overwrite existing passwords or regenerate existing hashes.
            try:
                user_count = User.query.count()
                if user_count == 0:
                    default_admin = User(
                        username='admin',
                        name='Admin User',
                        email='admin@inventory.ai',
                        role='admin',
                        is_active=True
                    )
                    default_admin.set_password('admin123')
                    db.session.add(default_admin)
                    db.session.commit()
                    app.logger.info("Default admin user created (admin / admin123).")
                else:
                    app.logger.info(f"Verified {user_count} existing user account(s). Preserving existing credentials.")
            except Exception as e:
                db.session.rollback()
                app.logger.warning(f"Admin verification notice: {e}")

        except Exception as e:
            app.logger.warning(f"Database schema verification notice: {e}")

    return app

app = create_app()

if __name__ == '__main__':
    # Only search for an available port in the parent process.
    # The Werkzeug reloader spawns a child process which will inherit the port.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    else:
        port = find_available_port(5000)
        os.environ['FLASK_RUN_PORT'] = str(port)
        def get_lan_ip():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(('8.8.8.8', 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
            except Exception:
                return '127.0.0.1'
        lan_ip = get_lan_ip()
        print("\n==================================================")
        print(" SMART INVENTORY AI FLASK SERVER")
        print("==================================================")
        print(f" -> Localhost:       http://localhost:{port}/")
        print(f" -> Localhost (IP):  http://127.0.0.1:{port}/")
        print(f" -> Local Network:   http://{lan_ip}:{port}/")
        print("==================================================\n")
        
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')
