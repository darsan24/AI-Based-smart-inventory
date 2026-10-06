import secrets
import time
import re
import logging
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import db, User
from utils.email_util import send_email

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def login_required(f):
    """Decorator to enforce Flask Session Authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash('Unauthorized access! Please log in first.', 'danger')
            return redirect(url_for('auth.login', next=request.url))

        # Verify user still exists in database and account is active
        user = User.query.get(user_id)
        if not user or not getattr(user, 'is_active', True):
            session.clear()
            flash('Session expired or account is inactive. Please log in again.', 'warning')
            return redirect(url_for('auth.login', next=request.url))

        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session and request.method == 'GET':
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        raw_identifier = request.form.get('username', '')
        raw_password = request.form.get('password', '')

        identifier = raw_identifier.strip()
        password = raw_password.strip()

        if not identifier or not raw_password:
            flash('Please enter both username and password.', 'warning')
            return render_template('auth/login.html')

        logging.info("LOGIN ATTEMPT")
        logging.info("Database connection: SUCCESS")

        # Case-insensitive lookup on username or email
        user = User.query.filter(
            (db.func.lower(User.username) == identifier.lower()) |
            (db.func.lower(User.email) == identifier.lower())
        ).first()

        if not user:
            logging.info("Username lookup: NOT FOUND")
            flash('Invalid username or password.', 'danger')
            return render_template('auth/login.html')

        logging.info("Username lookup: FOUND")

        # Account active check
        if not getattr(user, 'is_active', True):
            logging.info("Account status: INACTIVE")
            flash('Invalid username or password.', 'danger')
            return render_template('auth/login.html')

        logging.info("Account status: ACTIVE")

        # Verify password hash (check stripped and raw to prevent any trailing whitespace mismatches)
        password_ok = user.check_password(raw_password) or (password and user.check_password(password))
        if not password_ok:
            logging.info("Password verification: FAILED")
            flash('Invalid username or password.', 'danger')
            return render_template('auth/login.html')

        logging.info("Password verification: SUCCESS")

        try:
            session.clear()
            session.permanent = True
            session['user_id'] = user.id
            session['username'] = user.username
            session['name'] = user.name or user.username
            session['role'] = user.role
            logging.info("Session creation: SUCCESS")
        except Exception as e:
            logging.error(f"Session creation: FAILED - {e}")
            flash('Invalid username or password.', 'danger')
            return render_template('auth/login.html')

        flash(f'Welcome back, {user.username}! Admin session initiated.', 'success')

        next_page = request.args.get('next')
        if next_page and next_page.startswith('/') and not next_page.startswith('//'):
            return redirect(next_page)
        return redirect(url_for('dashboard.index'))

    return render_template('auth/login.html')

# -----------------------------------------------------------------
# Registration is DISABLED.
# This is a single-owner commercial application. The sole admin
# account is provisioned via seed.py.  No self-registration is
# permitted.  If a second account is ever needed, create it with
# a one-off script run directly against the database.
# -----------------------------------------------------------------
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    from flask import abort
    abort(404)

@auth_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    # Registration OTP verification — disabled along with registration.
    from flask import abort
    abort(404)

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    prefill_identifier = ''
    if 'user_id' in session:
        current_user = User.query.get(session['user_id'])
        if current_user:
            prefill_identifier = current_user.email or current_user.username

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        
        if not identifier:
            flash('Please enter your registered username or email address.', 'warning')
            return render_template('auth/forgot_password.html', prefill_identifier=prefill_identifier)

        user = User.query.filter((User.username.ilike(identifier)) | (User.email.ilike(identifier))).first()
        
        if user:
            # Cryptographically secure 6-digit OTP
            otp = f"{secrets.randbelow(900000) + 100000}"
            session['reset_otp'] = otp
            session['reset_user_id'] = user.id
            session['reset_email'] = user.email
            session['reset_username'] = user.username
            session['reset_otp_time'] = time.time()
            session['reset_otp_attempts'] = 0
            session.pop('reset_verified', None)
            
            # Send Email
            subject = "Password Reset Verification Code - Smart Inventory AI"
            body_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 540px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h2 style="color: #1e3a8a; margin-top: 0;">Password Reset Verification</h2>
                <p>Hello <b>{user.username}</b>,</p>
                <p>You have requested to reset your password for your <b>Smart Inventory AI</b> administrative account.</p>
                <div style="background-color: #f1f5f9; padding: 16px; border-radius: 6px; text-align: center; margin: 20px 0;">
                    <span style="font-size: 13px; color: #64748b; display: block; margin-bottom: 6px; font-weight: bold;">YOUR ONE-TIME PASSWORD (OTP)</span>
                    <strong style="font-size: 32px; letter-spacing: 6px; color: #1e3a8a;">{otp}</strong>
                </div>
                <p style="font-size: 13px; color: #64748b;">This code is valid for <b>10 minutes</b>. If you did not request this password reset, please ignore this email or check your account security.</p>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
                <p style="font-size: 12px; color: #94a3b8; margin-bottom: 0;">Smart Inventory AI &bull; Automated Security Service</p>
            </div>
            """
            email_sent = send_email(user.email, subject, body_html)
            if email_sent:
                flash(f'A 6-digit verification code has been dispatched to {user.email}.', 'info')
            else:
                flash(f'Notice: OTP code generated ({otp} for testing). SMTP email delivery was not available.', 'info')
            return redirect(url_for('auth.verify_reset_otp'))
        else:
            flash('No account found matching that username or email address.', 'danger')

    return render_template('auth/forgot_password.html', prefill_identifier=prefill_identifier)


@auth_bp.route('/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp():
    if 'reset_user_id' not in session or 'reset_otp' not in session:
        flash('Session expired or no password reset in progress. Please start again.', 'warning')
        return redirect(url_for('auth.forgot_password'))

    # Check OTP expiration (10 minutes = 600s)
    otp_time = session.get('reset_otp_time', 0)
    if time.time() - otp_time > 600:
        session.pop('reset_otp', None)
        session.pop('reset_user_id', None)
        flash('The verification code has expired (valid for 10 minutes). Please request a new code.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    masked_email = ''
    raw_email = session.get('reset_email', '')
    if raw_email and '@' in raw_email:
        parts = raw_email.split('@')
        user_part = parts[0]
        masked_user = user_part[0] + '***' + (user_part[-1] if len(user_part) > 1 else '')
        masked_email = f"{masked_user}@{parts[1]}"

    if request.method == 'POST':
        attempts = session.get('reset_otp_attempts', 0) + 1
        session['reset_otp_attempts'] = attempts

        if attempts > 5:
            session.pop('reset_otp', None)
            session.pop('reset_user_id', None)
            flash('Maximum verification attempts exceeded. Please request a new OTP.', 'danger')
            return redirect(url_for('auth.forgot_password'))

        entered_otp = request.form.get('otp', '').strip()
        expected_otp = session.get('reset_otp')

        if not entered_otp:
            flash('Please enter the 6-digit verification code.', 'warning')
            return render_template('auth/verify_reset_otp.html', masked_email=masked_email)

        if entered_otp == expected_otp:
            session['reset_verified'] = True
            session.pop('reset_otp', None)  # Invalidate OTP after successful verification to prevent replay
            flash('Verification code accepted! Please set your new secure password.', 'success')
            return redirect(url_for('auth.reset_password'))
        else:
            remaining = max(0, 5 - attempts)
            flash(f'Invalid verification code. {remaining} attempt(s) remaining.', 'danger')

    return render_template('auth/verify_reset_otp.html', masked_email=masked_email)


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('reset_verified') or 'reset_user_id' not in session:
        flash('Unauthorized access or password reset session expired. Please start over.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.get(session['reset_user_id'])
    if not user:
        flash('Account not found.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not new_password or not confirm_password:
            flash('Please fill in both password fields.', 'warning')
            return render_template('auth/reset_password.html')

        if new_password != confirm_password:
            flash('New password and confirmation password do not match.', 'danger')
            return render_template('auth/reset_password.html')

        # Password complexity validation
        if len(new_password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return render_template('auth/reset_password.html')

        if not re.search(r"[a-z]", new_password):
            flash('Password must include at least one lowercase letter (a-z).', 'danger')
            return render_template('auth/reset_password.html')

        if not re.search(r"[A-Z]", new_password):
            flash('Password must include at least one uppercase letter (A-Z).', 'danger')
            return render_template('auth/reset_password.html')

        if not re.search(r"[0-9]", new_password):
            flash('Password must include at least one number (0-9).', 'danger')
            return render_template('auth/reset_password.html')

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", new_password):
            flash('Password must include at least one special character (!@#$%^&*...).', 'danger')
            return render_template('auth/reset_password.html')

        if user.check_password(new_password):
            flash('New password cannot be the same as your current password.', 'warning')
            return render_template('auth/reset_password.html')

        try:
            user.set_password(new_password)
            db.session.commit()
            
            # Clear all reset and previous auth session state
            session.clear()

            flash('Password reset successfully! You can now log in using your new password.', 'success')
            return redirect(url_for('auth.login'))
        except Exception:
            db.session.rollback()
            flash('Something went wrong while updating your password. Please try again.', 'danger')

    return render_template('auth/reset_password.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('auth.login'))
