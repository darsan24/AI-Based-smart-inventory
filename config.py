import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'super-secret-inventory-ai-key-2026')
    
    # Primary MySQL URI: mysql+pymysql://username:password@localhost:3306/inventory_db
    # If MYSQL_URL environment variable is provided, use it.
    # Defaults to SQLite if MySQL is not explicitly configured or unavailable locally.
    MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', 'root')
    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'localhost')
    MYSQL_PORT = os.environ.get('MYSQL_PORT', '3306')
    MYSQL_DB = os.environ.get('MYSQL_DB', 'inventory_db')

    # Construct SQLAlchemy URI
    DEFAULT_MYSQL_URI = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
    FALLBACK_SQLITE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'inventory.db')}"

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', FALLBACK_SQLITE_URI)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TEMPLATES_AUTO_RELOAD = True

    # Session & Cookie Security (Stable across restarts)
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = False

    # Upload configurations
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB Max upload limit
    ALLOWED_EXTENSIONS = {'csv'}

    # AI Model configurations
    MODEL_DIR = os.path.join(BASE_DIR, 'ai', 'saved_models')
    PATCH_LENGTH = 7
    STRIDE = 3

    # Email configurations
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 465))
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', os.environ.get('SMTP_USERNAME', ''))
