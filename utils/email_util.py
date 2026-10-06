import smtplib
from email.message import EmailMessage
import logging
from config import Config

def send_email(to_email, subject, body_html):
    """Sends an HTML email using the configured SMTP settings."""
    try:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = Config.MAIL_DEFAULT_SENDER
        msg['To'] = to_email
        msg.set_content("Please enable HTML to view this message.")
        msg.add_alternative(body_html, subtype='html')

        # Using SMTP_SSL for port 465
        with smtplib.SMTP_SSL(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
            server.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
            server.send_message(msg)
            
        logging.info(f"Email successfully sent to {to_email}")
        return True
    except Exception as e:
        logging.error(f"Failed to send email to {to_email}: {str(e)}")
        return False

def check_and_send_low_stock_alert(product, was_low_stock=False):
    """
    Centralized inventory alert email dispatcher.
    Evaluates product stock level against administrator notification preferences:
      - email_alerts: Global master switch for automated email dispatch.
      - out_of_stock_alerts: Controls alerts when stock reaches exactly 0.
      - low_stock_alerts: Controls alerts when stock is at or below reorder level.
    """
    from models import User, Setting
    from datetime import datetime

    # 1. Global Master Check: Are automated alert emails enabled?
    if not Setting.get_bool('email_alerts', True):
        return False

    low_stock_enabled = Setting.get_bool('low_stock_alerts', True)
    out_of_stock_enabled = Setting.get_bool('out_of_stock_alerts', True)

    is_out_of_stock = (product.current_stock == 0)
    is_low_stock = (product.current_stock <= product.reorder_level)

    # 2. Evaluate Specific Stock Conditions
    if is_out_of_stock:
        if not out_of_stock_enabled:
            return False
        status_text = "OUT OF STOCK (0 units remaining)"
        alert_level = "CRITICAL OUT-OF-STOCK"
        subject = f"CRITICAL: Out of Stock Alert - {product.name} ({product.product_id_str})"
    elif is_low_stock:
        if not low_stock_enabled:
            return False
        status_text = f"RUNNING LOW ON STOCK ({product.current_stock} units remaining, Minimum Reorder Level: {product.reorder_level})"
        alert_level = "LOW STOCK WARNING"
        subject = f"WARNING: Low Stock Alert - {product.name} ({product.product_id_str})"
    else:
        # Stock is healthy, no alert needed
        return False

    # 3. Build & Dispatch Automated Alert Email
    body_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
        <h2 style="color: #1e3a8a; margin-top: 0;">Smart Inventory AI — Automated Stock Alert</h2>
        <div style="background-color: {'#fee2e2' if is_out_of_stock else '#fef3c7'}; padding: 12px 16px; border-radius: 6px; margin-bottom: 16px;">
            <strong style="color: {'#991b1b' if is_out_of_stock else '#92400e'};">{alert_level}</strong>
            <p style="margin: 4px 0 0 0; color: #334155;">Product <b>{product.name}</b> is currently <b>{status_text}</b>.</p>
        </div>
        
        <h4 style="color: #0f172a; margin-bottom: 8px;">Product Specifications</h4>
        <table style="width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 16px;">
            <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 6px 0; color: #64748b;">Product Code:</td><td style="padding: 6px 0; font-weight: bold; color: #0f172a;">{product.product_id_str}</td></tr>
            <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 6px 0; color: #64748b;">Product Name:</td><td style="padding: 6px 0; font-weight: bold; color: #0f172a;">{product.name}</td></tr>
            <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 6px 0; color: #64748b;">Category / Brand:</td><td style="padding: 6px 0; color: #0f172a;">{product.category} / {product.brand}</td></tr>
            <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 6px 0; color: #64748b;">Current Stock:</td><td style="padding: 6px 0; font-weight: bold; color: {'#dc2626' if is_out_of_stock else '#d97706'};">{product.current_stock} Units</td></tr>
            <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 6px 0; color: #64748b;">Minimum Reorder Level:</td><td style="padding: 6px 0; color: #0f172a;">{product.reorder_level} Units</td></tr>
            <tr><td style="padding: 6px 0; color: #64748b;">Timestamp:</td><td style="padding: 6px 0; color: #64748b;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
        </table>
        
        <div style="background-color: #f8fafc; padding: 12px; border-left: 4px solid #2563eb; border-radius: 4px; margin-bottom: 16px;">
            <strong style="color: #1e3a8a;">Recommended Action:</strong>
            <p style="margin: 4px 0 0 0; color: #475569; font-size: 13px;">Please initiate a supplier replenishment purchase order immediately to prevent fulfillment delays.</p>
        </div>
        
        <p style="font-size: 12px; color: #94a3b8; margin-bottom: 0;">This is an automated system notification from Smart Inventory AI.</p>
    </div>
    """
    
    # Fetch admin recipients dynamically
    try:
        admin_users = User.query.filter_by(role='admin').all()
        recipients = [u.email for u in admin_users if u.email and '@' in u.email and not u.email.endswith('@inventory.ai')]
    except Exception:
        recipients = []

    if not recipients:
        recipients = [getattr(Config, 'MAIL_DEFAULT_SENDER', 'krishkrishna3107@gmail.com')]

    sent_any = False
    for target in set(recipients):
        if send_email(target, subject, body_html):
            sent_any = True
    return sent_any

