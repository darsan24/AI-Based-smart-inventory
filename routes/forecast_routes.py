"""
Forecast Routes — PatchTST AI Demand Forecasting.

All date operations use IST (Asia/Kolkata) via centralized date utility.
The backend is the authoritative source for all forecast dates, predictions,
confidence intervals, and model metadata.
"""

from datetime import timedelta
import json
import threading
import traceback
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from models import db, Product, ForecastPrediction, Sale, Setting
from routes.auth_routes import login_required
from ai.patchtst_model import train_and_forecast_product, get_baseline_comparison_summary
from ai.reorder_engine import generate_reorder_recommendation
from ai.shap_explainability import InventorySHAPExplainer
from ai.demand_reasoning import generate_ai_demand_reason
from utils.date_utils import get_current_date_ist, format_date_display, get_latest_sale_date

forecast_bp = Blueprint('forecast', __name__, url_prefix='/forecast')

# In-memory progress tracker for background retraining
retrain_progress = {
    "running": False,
    "current": 0,
    "total": 0,
    "current_product": None,
    "done": True,
    "results": []
}


def run_retrain_all(app):
    """
    Background worker function for retraining all products sequentially.
    Runs inside app.app_context() to ensure database access works across threads.
    """
    with app.app_context():
        try:
            products = Product.query.order_by(
                db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc()
            ).all()
            retrain_progress.update(
                running=True,
                current=0,
                total=len(products),
                done=False,
                results=[]
            )
            for i, p in enumerate(products, start=1):
                retrain_progress["current"] = i
                retrain_progress["current_product"] = p.name
                try:
                    train_and_forecast_product(db.session, p.id)
                    generate_reorder_recommendation(db.session, p.id)
                    retrain_progress["results"].append({
                        "product": p.name,
                        "product_id_str": p.product_id_str,
                        "ok": True
                    })
                except Exception as e:
                    print(f"[Forecast] retrain_all — error on {p.product_id_str} ({p.name}): {e}")
                    traceback.print_exc()
                    retrain_progress["results"].append({
                        "product": p.name,
                        "product_id_str": p.product_id_str,
                        "ok": False,
                        "error": str(e)
                    })
        except Exception as e:
            print(f"[Forecast] run_retrain_all fatal error: {e}")
            traceback.print_exc()
        finally:
            retrain_progress.update(running=False, done=True, current_product=None)
            try:
                db.session.remove()
            except Exception:
                pass



@forecast_bp.route('/')
@login_required
def index():
    products = Product.query.order_by(db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc()).all()
    selected_product_id = request.args.get('product_id', type=int)

    if not selected_product_id and products:
        selected_product_id = products[0].id

    selected_product = Product.query.get(selected_product_id) if selected_product_id else None

    # Load forecasting configuration defaults
    default_horizon = int(Setting.get('forecast_horizon', '15'))
    shap_enabled = Setting.get_bool('shap_explainability', True)

    predictions = []
    ai_reasoning = None
    shap_analysis = None
    forecast_meta = {}
    error_message = None

    if selected_product:
        predictions = (
            ForecastPrediction.query
            .filter_by(product_id=selected_product.id)
            .order_by(ForecastPrediction.horizon_days.asc())
            .all()
        )

        # Build forecast metadata from the first prediction (same for all horizons)
        if predictions:
            first_pred = predictions[0]
            first_dict = first_pred.to_dict()
            forecast_meta = {
                'generation_date': format_date_display(first_pred.forecast_generation_date),
                'last_historical_date': format_date_display(first_pred.last_historical_date),
                'model_method': first_pred.model_method or 'PatchTST',
                'model_mae': float(first_pred.model_mae) if first_pred.model_mae is not None else None,
                'model_rmse': float(first_pred.model_rmse) if first_pred.model_rmse is not None else None,
                'baseline_method': first_pred.baseline_method or '14-Day Moving Average',
                'baseline_mae': float(first_pred.baseline_mae) if first_pred.baseline_mae is not None else None,
                'baseline_rmse': float(first_pred.baseline_rmse) if first_pred.baseline_rmse is not None else None,
                'improvement_percent': first_dict.get('improvement_percent'),
                'data_confidence': first_pred.data_confidence or 'Medium',
            }

        # Get forecast matching configured default horizon for reasoning
        f_pred = next((p for p in predictions if p.horizon_days == default_horizon), None)
        if not f_pred and predictions:
            f_pred = predictions[0]
        f_val = float(f_pred.predicted_demand) if f_pred else float(selected_product.reorder_level * 1.5)

        if shap_enabled:
            try:
                explainer = InventorySHAPExplainer()
                shap_analysis = explainer.explain_product_prediction(
                    selected_product, f_val, db_session=db.session
                )
            except Exception as e:
                print(f"[Forecast] SHAP analysis error: {e}")
                traceback.print_exc()
        else:
            shap_analysis = None

        try:
            ai_reasoning = generate_ai_demand_reason(
                selected_product, f_val, shap_analysis, db.session
            )
        except Exception as e:
            print(f"[Forecast] AI reasoning error: {e}")
            traceback.print_exc()

    # All predictions summary for table
    all_predictions = ForecastPrediction.query.order_by(ForecastPrediction.forecast_date.asc()).all()

    # Overall baseline comparison summary across all products
    baseline_summary = get_baseline_comparison_summary(db.session)

    today = get_latest_sale_date()

    return render_template(
        'forecast/index.html',
        products=products,
        selected_product=selected_product,
        predictions=predictions,
        all_predictions=all_predictions,
        ai_reasoning=ai_reasoning,
        shap_analysis=shap_analysis,
        shap_enabled=shap_enabled,
        default_horizon=default_horizon,
        forecast_meta=forecast_meta,
        baseline_summary=baseline_summary,
        error_message=error_message,
        current_date=format_date_display(today),
    )


@forecast_bp.route('/train', methods=['POST'])
@login_required
def train_model():
    product_id = request.form.get('product_id', type=int)

    try:
        if product_id:
            result = train_and_forecast_product(db.session, product_id)
            generate_reorder_recommendation(db.session, product_id)
            p = Product.query.get(product_id)
            if result:
                method = result[0].model_method if result else 'PatchTST'
                flash(
                    f'Model retrained successfully for "{p.name}" using {method}!',
                    'success'
                )
            else:
                flash(f'Could not generate forecast for "{p.name}". Product may not exist.', 'warning')
        else:
            # Retrain for all products
            products = Product.query.order_by(
                db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc()
            ).all()
            success_count = 0
            for p in products:
                try:
                    train_and_forecast_product(db.session, p.id)
                    generate_reorder_recommendation(db.session, p.id)
                    success_count += 1
                except Exception as e:
                    print(f"[Forecast] Error training product {p.product_id_str}: {e}")
                    continue
            flash(
                f'PatchTST Demand Forecasting executed for {success_count}/{len(products)} products!',
                'success'
            )
    except Exception as e:
        print(f"[Forecast] Training error: {e}")
        traceback.print_exc()
        flash(f'Error during model training: {str(e)}', 'danger')

    return redirect(url_for('forecast.index', product_id=product_id if product_id else ''))


@forecast_bp.route('/retrain_all', methods=['POST'])
@login_required
def retrain_all():
    """
    Starts background retraining of all products.
    Returns immediately with 200 and started: True.
    If a job is already in flight, returns 409 so the frontend can resume polling.
    """
    if retrain_progress["running"]:
        return jsonify({"error": "A retrain is already running", "already_running": True}), 409

    try:
        total_products = Product.query.count()
    except Exception:
        total_products = 0

    retrain_progress.update(
        running=True,
        current=0,
        total=total_products,
        current_product="Starting...",
        done=False,
        results=[]
    )
    thread = threading.Thread(
        target=run_retrain_all,
        args=(current_app._get_current_object(),),
        daemon=True
    )
    thread.start()
    return jsonify({"started": True, "total": total_products})


@forecast_bp.route('/retrain_all/status', methods=['GET'])
@login_required
def retrain_all_status():
    """
    Returns current in-memory retraining progress and results.
    Polled periodically by the frontend.
    """
    results = retrain_progress.get("results", [])
    success_count = sum(1 for r in results if r.get("ok"))
    failed = [
        {"name": r["product"], "product_id_str": r.get("product_id_str", ""), "error": r.get("error")}
        for r in results if not r.get("ok")
    ]
    return jsonify({
        "running": retrain_progress.get("running", False),
        "current": retrain_progress.get("current", 0),
        "total": retrain_progress.get("total", 0),
        "current_product": retrain_progress.get("current_product"),
        "done": retrain_progress.get("done", True),
        "results": results,
        "success_count": success_count,
        "failed": failed
    })


@forecast_bp.route('/explain/<int:product_id>')
@login_required
def explain(product_id):
    product = Product.query.get_or_404(product_id)

    # Check if SHAP explainability is enabled
    shap_enabled = Setting.get_bool('shap_explainability', True)
    if not shap_enabled:
        flash('SHAP Explainability is currently disabled.', 'info')
        return redirect(url_for('forecast.index', product_id=product_id))

    # Fetch configured default horizon forecast
    default_horizon = int(Setting.get('forecast_horizon', '15'))
    forecast = (
        ForecastPrediction.query
        .filter_by(product_id=product.id, horizon_days=default_horizon)
        .order_by(ForecastPrediction.created_at.desc())
        .first()
    )
    if not forecast:
        forecast = ForecastPrediction.query.filter_by(product_id=product.id).order_by(ForecastPrediction.created_at.desc()).first()
    predicted_demand = float(forecast.predicted_demand) if forecast else float(product.reorder_level * 1.5)

    try:
        explainer = InventorySHAPExplainer()
        shap_analysis = explainer.explain_product_prediction(
            product, predicted_demand, db_session=db.session
        )
    except Exception as e:
        print(f"[Forecast] SHAP explain error: {e}")
        traceback.print_exc()
        shap_analysis = {
            'base_value': 0,
            'predicted_demand': predicted_demand,
            'feature_contributions': [],
            'summary_plot_b64': None,
            'explanation_text': f'Unable to generate SHAP explanation: {str(e)}'
        }

    return render_template(
        'forecast/explain.html',
        product=product,
        predicted_demand=predicted_demand,
        shap_analysis=shap_analysis
    )


@forecast_bp.route('/analytics')
@login_required
def analytics():
    products = Product.query.order_by(db.cast(db.func.substr(Product.product_id_str, 5), db.Integer).asc()).all()
    today = get_latest_sale_date()

    total_forecast_15d = (
        db.session.query(db.func.sum(ForecastPrediction.predicted_demand))
        .filter(ForecastPrediction.horizon_days == 15)
        .scalar() or 0.0
    )

    product_data = []
    thirty_days_ago = today - timedelta(days=30)

    for p in products:
        f_7 = ForecastPrediction.query.filter_by(product_id=p.id, horizon_days=7).order_by(ForecastPrediction.created_at.desc()).first()
        f_15 = ForecastPrediction.query.filter_by(product_id=p.id, horizon_days=15).order_by(ForecastPrediction.created_at.desc()).first()
        f_30 = ForecastPrediction.query.filter_by(product_id=p.id, horizon_days=30).order_by(ForecastPrediction.created_at.desc()).first()

        sales = db.session.query(db.func.sum(Sale.quantity_sold)).filter(Sale.product_id == p.id, Sale.sale_date >= thirty_days_ago).scalar() or 0

        product_data.append({
            'id': p.id,
            'name': p.name,
            'product_type': p.product_type,
            'category': p.category,
            'brand': p.brand,
            'current_stock': p.current_stock,
            'reorder_level': p.reorder_level,
            'forecast_7d': float(f_7.predicted_demand) if f_7 else float(p.reorder_level * 0.7),
            'forecast_15d': float(f_15.predicted_demand) if f_15 else float(p.reorder_level * 1.5),
            'forecast_30d': float(f_30.predicted_demand) if f_30 else float(p.reorder_level * 3.0),
            'sales_30d': int(sales)
        })

    return render_template(
        'forecast/analytics.html',
        product_data_json=json.dumps(product_data),
        total_forecast_15d=total_forecast_15d
    )
