import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import os
from fpdf import FPDF
from app import app
from models import db, ForecastPrediction, Product
from utils.date_utils import get_current_datetime_ist, format_date_display
from services.report_service import get_filtered_forecast_report

def export_forecast_pdf():
    with app.app_context():
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.set_auto_page_break(auto=True, margin=12)
        pdf.add_page()
        
        gen_time_display = get_current_datetime_ist().strftime('%d %b %Y, %I:%M %p IST')

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

        forecast_data = get_filtered_forecast_report()
        forecasts = forecast_data['forecasts']

        headers = ['Code', 'Product Name', 'Category', 'Brand', 'Stock', 'Horizon', 'Ref Date', 'Target Date', 'Predicted', 'Confidence']
        col_widths = [22, 60, 32, 25, 14, 18, 26, 26, 26, 26]

        pdf.set_fill_color(37, 99, 235)
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
        
        output_path = r"c:\Users\Selva\Desktop\demand_forecast_report.pdf"
        try:
            pdf.output(output_path)
            print(f"Successfully saved to {output_path}")
        except Exception as e:
            print(f"PDF Output notice: {e}")

if __name__ == '__main__':
    export_forecast_pdf()
