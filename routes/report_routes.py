"""
Report Routes — Operational and Analytical Reports with CSV and PDF Export.

All date operations use IST (Asia/Kolkata) via centralized date utilities.
All reports support interactive multi-criteria filtering and consistent
date/metadata alignment.
"""

import csv
import io
from datetime import datetime
from flask import Blueprint, render_template, request, Response, make_response
from fpdf import FPDF
from models import db, Product, Sale, InventoryTransaction, ForecastPrediction
from routes.auth_routes import login_required
from utils.date_utils import (
    get_current_date_ist,
    get_current_datetime_ist,
    format_date_display,
    format_date_iso
)
from services.report_service import (
    get_report_filter_options,
    get_filtered_forecast_report,
    get_filtered_inventory_report,
    get_filtered_sales_report,
    get_filtered_low_stock_report
)

report_bp = Blueprint('reports', __name__, url_prefix='/reports')


@report_bp.route('/')
@login_required
def index():
    report_type = request.args.get('type', 'inventory')
    horizon = request.args.get('horizon', '')
    category = request.args.get('category', '')
    brand = request.args.get('brand', '')
    product_type = request.args.get('product_type', '')
    search_query = request.args.get('q', '')

    filter_options = get_report_filter_options()

    active_filters = {
        'horizon': horizon,
        'category': category,
        'brand': brand,
        'product_type': product_type,
        'q': search_query,
    }

    products = []
    sales = []
    forecast_data = {}
    low_stock = []

    if report_type == 'inventory':
        products = get_filtered_inventory_report(category, brand, product_type, search_query)
    elif report_type == 'sales':
        sales = get_filtered_sales_report(category, brand, product_type, search_query)
    elif report_type == 'forecast':
        forecast_data = get_filtered_forecast_report(horizon, category, brand, product_type, search_query)
    elif report_type == 'low_stock':
        low_stock = get_filtered_low_stock_report(category, brand, product_type, search_query)

    today = get_current_date_ist()

    return render_template(
        'reports/index.html',
        report_type=report_type,
        products=products,
        sales=sales,
        forecast_data=forecast_data,
        forecasts=forecast_data.get('forecasts', []),
        low_stock=low_stock,
        filter_options=filter_options,
        active_filters=active_filters,
        current_date_display=format_date_display(today),
    )


@report_bp.route('/export/<report_type>')
@login_required
def export_csv(report_type):
    horizon = request.args.get('horizon', '')
    category = request.args.get('category', '')
    brand = request.args.get('brand', '')
    product_type = request.args.get('product_type', '')
    search_query = request.args.get('q', '')

    output = io.StringIO()
    writer = csv.writer(output)
    timestamp = get_current_datetime_ist().strftime('%Y%m%d_%H%M%S')

    if report_type == 'inventory':
        writer.writerow([
            'Product ID', 'Product Type', 'Name', 'Category', 'Brand',
            'Cost Price (INR)', 'Selling Price (INR)', 'Current Stock',
            'Reorder Level', 'Safety Stock', 'Max Stock', 'Status', 'Supplier'
        ])
        products = get_filtered_inventory_report(category, brand, product_type, search_query)
        for p in products:
            status = 'LOW STOCK' if p.is_low_stock else 'OK'
            writer.writerow([
                p.product_id_str, p.product_type, p.name, p.category, p.brand,
                f"{float(p.cost_price or 0):.2f}", f"{float(p.price or 0):.2f}",
                p.current_stock, p.reorder_level, p.safety_stock, p.maximum_stock,
                status, p.supplier_name or 'N/A'
            ])
        filename = f'inventory_report_{timestamp}.csv'

    elif report_type == 'sales':
        writer.writerow([
            'Sale ID', 'Sale Date', 'Product Code', 'Product Name',
            'Category', 'Brand', 'Quantity Sold', 'Total Revenue (INR)'
        ])
        sales = get_filtered_sales_report(category, brand, product_type, search_query, limit=1000)
        for s in sales:
            writer.writerow([
                s.id,
                format_date_iso(s.sale_date),
                s.product.product_id_str if s.product else '',
                s.product.name if s.product else '',
                s.product.category if s.product else '',
                s.product.brand if s.product else '',
                s.quantity_sold,
                f"{float(s.total_price):.2f}"
            ])
        filename = f'sales_report_{timestamp}.csv'

    elif report_type == 'forecast':
        writer.writerow([
            'Product Code', 'Product Name', 'Product Type', 'Category', 'Brand',
            'Current Stock', 'Reorder Level', 'Forecast Horizon (Days)',
            'Forecast Reference Date (IST)', 'Forecast Target Date (IST)',
            'Predicted Demand (Units)', 'Confidence Lower (Units)', 'Confidence Upper (Units)',
            'Model Method', 'Data Confidence', 'Last Historical Sales Date'
        ])
        forecast_data = get_filtered_forecast_report(horizon, category, brand, product_type, search_query)
        for f in forecast_data['forecasts']:
            p = f.product
            writer.writerow([
                p.product_id_str if p else '',
                p.name if p else '',
                p.product_type if p else '',
                p.category if p else '',
                p.brand if p else '',
                p.current_stock if p else 0,
                p.reorder_level if p else 0,
                f.horizon_days,
                format_date_iso(f.forecast_generation_date),
                format_date_iso(f.forecast_date),
                f"{float(f.predicted_demand):.1f}",
                f"{float(f.confidence_lower):.1f}" if f.confidence_lower is not None else '',
                f"{float(f.confidence_upper):.1f}" if f.confidence_upper is not None else '',
                f.model_method or 'PatchTST',
                f.data_confidence or 'Medium',
                format_date_iso(f.last_historical_date) if f.last_historical_date else 'N/A'
            ])
        filename = f'demand_forecast_report_{timestamp}.csv'

    elif report_type == 'low_stock':
        writer.writerow([
            'Product ID', 'Product Type', 'Name', 'Category', 'Brand',
            'Current Stock', 'Reorder Level', 'Deficit', 'Supplier'
        ])
        low_stock = get_filtered_low_stock_report(category, brand, product_type, search_query)
        for p in low_stock:
            deficit = p.reorder_level - p.current_stock
            writer.writerow([
                p.product_id_str, p.product_type, p.name, p.category, p.brand,
                p.current_stock, p.reorder_level, deficit, p.supplier_name or 'N/A'
            ])
        filename = f'low_stock_report_{timestamp}.csv'

    else:
        return "Invalid report type", 400

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-type'] = 'text/csv; charset=utf-8'
    return response


@report_bp.route('/export_pdf/<report_type>')
@login_required
def export_pdf(report_type):
    horizon = request.args.get('horizon', '')
    category = request.args.get('category', '')
    brand = request.args.get('brand', '')
    product_type = request.args.get('product_type', '')
    search_query = request.args.get('q', '')

    timestamp = get_current_datetime_ist().strftime('%Y%m%d_%H%M%S')
    gen_time_display = get_current_datetime_ist().strftime('%d %b %Y, %I:%M %p IST')

    if report_type == 'forecast':
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.set_auto_page_break(auto=True, margin=12)
        pdf.add_page()
        
        # Header title
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, txt="Smart Inventory AI - Demand Forecasting Report", ln=True, align='C')
        pdf.set_font("Arial", size=9)
        pdf.cell(0, 5, txt=f"Report Generated: {gen_time_display} | Target Date Formula: Reference Date + Horizon", ln=True, align='C')
        
        # AI vs Baseline Accuracy Advantage Stat Line
        try:
            from ai.patchtst_model import get_baseline_comparison_summary
            b_summary = get_baseline_comparison_summary(db.session)
            if b_summary and b_summary.get('products_compared', 0) > 0:
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(109, 40, 217)
                pdf.cell(0, 5, txt=f"AI Performance Edge: PatchTST outperforms 14-day moving average by +{b_summary['average_improvement_percent']}% across {b_summary['products_compared']} products", ln=True, align='C')
                pdf.set_text_color(0, 0, 0)
        except Exception:
            pass
        pdf.ln(3)

        forecast_data = get_filtered_forecast_report(horizon, category, brand, product_type, search_query)
        forecasts = forecast_data['forecasts']

        # Table headers (Total printable width ~ 275mm in A4 Landscape)
        # Columns: Code(22), Product Name(60), Category(35), Brand(25), Stock(15), Horizon(18), Ref Date(26), Target Date(26), Demand(25), Conf(23)
        headers = ['Code', 'Product Name', 'Category', 'Brand', 'Stock', 'Horizon', 'Ref Date', 'Target Date', 'Predicted', 'Confidence']
        col_widths = [22, 60, 32, 25, 14, 18, 26, 26, 26, 26]

        pdf.set_fill_color(37, 99, 235) # Primary blue
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", 'B', 8)
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 8, header, border=1, fill=True, align='C')
        pdf.ln()

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", size=8)

        fill = False
        for f in forecasts:
            p = f.product
            code = p.product_id_str if p else ''
            name = (p.name[:32] + '..') if p and len(p.name) > 34 else (p.name if p else '')
            cat = (p.category[:17] + '..') if p and len(p.category) > 19 else (p.category if p else '')
            br = (p.brand[:13] + '..') if p and len(p.brand) > 15 else (p.brand if p else '')
            stock_str = str(p.current_stock) if p else '0'
            h_str = f"{f.horizon_days} Days"
            ref_date_str = format_date_display(f.forecast_generation_date)
            target_date_str = format_date_display(f.forecast_date)
            demand_str = f"{float(f.predicted_demand):.1f} u"
            conf_str = f"[{float(f.confidence_lower):.0f}-{float(f.confidence_upper):.0f}]" if f.confidence_lower is not None else "N/A"

            if fill:
                pdf.set_fill_color(245, 247, 250)
            else:
                pdf.set_fill_color(255, 255, 255)

            pdf.cell(col_widths[0], 7, code, border=1, fill=fill, align='C')
            pdf.cell(col_widths[1], 7, name, border=1, fill=fill, align='L')
            pdf.cell(col_widths[2], 7, cat, border=1, fill=fill, align='L')
            pdf.cell(col_widths[3], 7, br, border=1, fill=fill, align='L')
            pdf.cell(col_widths[4], 7, stock_str, border=1, fill=fill, align='C')
            pdf.cell(col_widths[5], 7, h_str, border=1, fill=fill, align='C')
            pdf.cell(col_widths[6], 7, ref_date_str, border=1, fill=fill, align='C')
            pdf.cell(col_widths[7], 7, target_date_str, border=1, fill=fill, align='C')
            pdf.cell(col_widths[8], 7, demand_str, border=1, fill=fill, align='R')
            pdf.cell(col_widths[9], 7, conf_str, border=1, fill=fill, align='C')
            pdf.ln()
            fill = not fill

        filename = f'demand_forecast_report_{timestamp}.pdf'

    elif report_type == 'inventory':
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.set_auto_page_break(auto=True, margin=12)
        pdf.add_page()
        
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, txt="Smart Inventory AI - Inventory Status Report", ln=True, align='C')
        pdf.set_font("Arial", size=9)
        pdf.cell(0, 6, txt=f"Report Generated: {gen_time_display}", ln=True, align='C')
        pdf.ln(3)

        products = get_filtered_inventory_report(category, brand, product_type, search_query)
        headers = ['Code', 'Type', 'Product Name', 'Category', 'Brand', 'Cost (INR)', 'Price (INR)', 'Stock', 'Reorder', 'Status']
        col_widths = [22, 26, 65, 35, 26, 25, 25, 16, 16, 22]

        pdf.set_fill_color(37, 99, 235)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", 'B', 8)
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 8, header, border=1, fill=True, align='C')
        pdf.ln()

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", size=8)

        fill = False
        for p in products:
            status = 'LOW STOCK' if p.is_low_stock else 'OK'
            name = (p.name[:35] + '..') if len(p.name) > 37 else p.name
            cat = (p.category[:18] + '..') if len(p.category) > 20 else p.category
            br = (p.brand[:14] + '..') if len(p.brand) > 16 else p.brand

            if fill:
                pdf.set_fill_color(245, 247, 250)
            else:
                pdf.set_fill_color(255, 255, 255)

            pdf.cell(col_widths[0], 7, str(p.product_id_str), border=1, fill=fill, align='C')
            pdf.cell(col_widths[1], 7, str(p.product_type), border=1, fill=fill, align='L')
            pdf.cell(col_widths[2], 7, name, border=1, fill=fill, align='L')
            pdf.cell(col_widths[3], 7, cat, border=1, fill=fill, align='L')
            pdf.cell(col_widths[4], 7, br, border=1, fill=fill, align='L')
            pdf.cell(col_widths[5], 7, f"{float(p.cost_price or 0):,.2f}", border=1, fill=fill, align='R')
            pdf.cell(col_widths[6], 7, f"{float(p.price or 0):,.2f}", border=1, fill=fill, align='R')
            pdf.cell(col_widths[7], 7, str(p.current_stock), border=1, fill=fill, align='C')
            pdf.cell(col_widths[8], 7, str(p.reorder_level), border=1, fill=fill, align='C')
            pdf.cell(col_widths[9], 7, status, border=1, fill=fill, align='C')
            pdf.ln()
            fill = not fill

        filename = f'inventory_report_{timestamp}.pdf'

    elif report_type == 'sales':
        pdf = FPDF(orientation='P', unit='mm', format='A4')
        pdf.set_auto_page_break(auto=True, margin=12)
        pdf.add_page()
        
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, txt="Smart Inventory AI - Sales Transaction Report", ln=True, align='C')
        pdf.set_font("Arial", size=9)
        pdf.cell(0, 6, txt=f"Report Generated: {gen_time_display}", ln=True, align='C')
        pdf.ln(3)

        sales = get_filtered_sales_report(category, brand, product_type, search_query, limit=500)
        headers = ['ID', 'Date', 'Product Code', 'Product Name', 'Qty', 'Total (INR)']
        col_widths = [16, 28, 28, 70, 18, 30]

        pdf.set_fill_color(37, 99, 235)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", 'B', 9)
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 8, header, border=1, fill=True, align='C')
        pdf.ln()

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", size=8)

        fill = False
        for s in sales:
            prod_name = s.product.name if s.product else ''
            prod_name = (prod_name[:38] + '..') if len(prod_name) > 40 else prod_name
            code = s.product.product_id_str if s.product else ''
            date_str = format_date_display(s.sale_date)

            if fill:
                pdf.set_fill_color(245, 247, 250)
            else:
                pdf.set_fill_color(255, 255, 255)

            pdf.cell(col_widths[0], 7, f"#{s.id}", border=1, fill=fill, align='C')
            pdf.cell(col_widths[1], 7, date_str, border=1, fill=fill, align='C')
            pdf.cell(col_widths[2], 7, code, border=1, fill=fill, align='C')
            pdf.cell(col_widths[3], 7, prod_name, border=1, fill=fill, align='L')
            pdf.cell(col_widths[4], 7, str(s.quantity_sold), border=1, fill=fill, align='C')
            pdf.cell(col_widths[5], 7, f"{float(s.total_price):,.2f}", border=1, fill=fill, align='R')
            pdf.ln()
            fill = not fill

        filename = f'sales_report_{timestamp}.pdf'

    elif report_type == 'low_stock':
        pdf = FPDF(orientation='P', unit='mm', format='A4')
        pdf.set_auto_page_break(auto=True, margin=12)
        pdf.add_page()
        
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, txt="Smart Inventory AI - Low Stock Alert Report", ln=True, align='C')
        pdf.set_font("Arial", size=9)
        pdf.cell(0, 6, txt=f"Report Generated: {gen_time_display}", ln=True, align='C')
        pdf.ln(3)

        low_stock = get_filtered_low_stock_report(category, brand, product_type, search_query)
        headers = ['Code', 'Product Name', 'Category', 'Stock', 'Threshold', 'Deficit']
        col_widths = [26, 70, 38, 18, 22, 18]

        pdf.set_fill_color(220, 38, 38) # Red for low stock
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", 'B', 9)
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 8, header, border=1, fill=True, align='C')
        pdf.ln()

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", size=8)

        fill = False
        for p in low_stock:
            deficit = p.reorder_level - p.current_stock
            name = (p.name[:38] + '..') if len(p.name) > 40 else p.name
            cat = (p.category[:20] + '..') if len(p.category) > 22 else p.category

            if fill:
                pdf.set_fill_color(245, 247, 250)
            else:
                pdf.set_fill_color(255, 255, 255)

            pdf.cell(col_widths[0], 7, str(p.product_id_str), border=1, fill=fill, align='C')
            pdf.cell(col_widths[1], 7, name, border=1, fill=fill, align='L')
            pdf.cell(col_widths[2], 7, cat, border=1, fill=fill, align='L')
            pdf.cell(col_widths[3], 7, str(p.current_stock), border=1, fill=fill, align='C')
            pdf.cell(col_widths[4], 7, str(p.reorder_level), border=1, fill=fill, align='C')
            pdf.cell(col_widths[5], 7, f"+{deficit}", border=1, fill=fill, align='C')
            pdf.ln()
            fill = not fill

        filename = f'low_stock_report_{timestamp}.pdf'

    else:
        return "Invalid report type", 400

    pdf_bytes = pdf.output(dest='S')
    if isinstance(pdf_bytes, str):
        pdf_bytes = pdf_bytes.encode('latin1')
    elif isinstance(pdf_bytes, bytearray):
        pdf_bytes = bytes(pdf_bytes)

    response = make_response(pdf_bytes)
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-type'] = 'application/pdf'
    return response


@report_bp.route('/analytics')
@login_required
def analytics():
    from services.inventory_kpi_service import compute_inventory_kpis

    kpis = compute_inventory_kpis(analysis_days=90)

    return render_template(
        'analytics/index.html',
        kpis=kpis,
        turnover_ratio=kpis['turnover_ratio'],
        total_inventory_value=kpis['total_inventory_cost'],
        dead_stock_value=kpis['dead_stock_value'],
        dead_stock_products=kpis['dead_stock_products'],
        fast_moving=kpis['fast_moving'],
        slow_moving=kpis['slow_moving'],
    )
