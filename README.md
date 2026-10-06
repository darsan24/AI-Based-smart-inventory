# AI-Based Smart Inventory Management System

An enterprise-grade, intelligent inventory management system powered by deep learning (**PatchTST**), explainable AI (**SHAP**), and real-time operational analytics.

---

## 🚀 Key Features

- **AI Demand Forecasting (PatchTST)**: Deep-learning time-series forecasting architecture leveraging patched token transformers for multi-horizon demand prediction.
- **Explainable AI (SHAP)**: Granular feature attribution providing human-interpretable reasoning for demand trends, seasonality, and promotional spikes.
- **Automated Reorder Engine**: Dynamic calculations for safety stock, minimum reorder thresholds, and optimal batch reorder quantities.
- **ABC / XYZ Inventory Matrix**: 9-box matrix classification segmenting products by revenue contribution (ABC) and demand variability (XYZ).
- **Interactive Executive Dashboard**: Real-time KPI cards, stock turnover rates, critical out-of-stock and low-stock monitor, and trends visualization.
- **Stock Alert System**: Automated email notifications via SMTP for critical low-stock and out-of-stock items.
- **Data Ingestion & Reports**: CSV dataset uploads, automatic data validation, and exportable PDF/CSV reports.
- **Role-Based Access Control**: Secure session management and authentication supporting Admin and Staff roles.

---

## 🛠️ Technology Stack

- **Backend**: Python 3.12, Flask, Flask-SQLAlchemy, Werkzeug
- **AI / Machine Learning**: PyTorch, SHAP, Scikit-learn, NumPy, Pandas
- **Database**: SQLite (default fallback) / MySQL (production)
- **Frontend**: HTML5, Vanilla CSS, Bootstrap, Chart.js
- **Document Generation**: fpdf2

---

## 📦 Project Structure

```text
├── ai/                      # AI models, PatchTST architecture, SHAP explainability & reorder logic
├── data/                    # Real cleaned product and historical sales datasets
├── database/                # Database schemas and DDL scripts
├── dataset/                 # Sample upload templates and test data
├── routes/                  # Flask Blueprint route handlers (auth, dashboard, inventory, sales, AI)
├── scripts/                 # Utility scripts for exports, migrations, and testing
├── services/                # Business logic services (KPIs, report generation)
├── static/                  # CSS styles, JavaScript assets, and UI screenshots
├── templates/               # Jinja2 HTML templates for all views
├── utils/                   # Utility helpers (date formatting, email dispatching)
├── .env.example             # Environment variable template
├── app.py                   # Application entry point and factory
├── config.py                # Centralized configuration settings
├── models.py                # SQLAlchemy ORM models
├── requirements.txt         # Python project dependencies
├── seed.py                  # Database seeding and AI training pipeline
└── test_auth_audit.py       # Automated authentication and security tests
```

---

## ⚡ Quick Start Guide

### 1. Prerequisites
- Python 3.10+ (Python 3.12 recommended)
- Git

### 2. Clone Repository
```bash
git clone https://github.com/darsan24/AI-Based-smart-inventory.git
cd AI-Based-smart-inventory
```

### 3. Create & Activate Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables
Copy `.env.example` to `.env` and update your settings as needed:
```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

### 6. Initialize & Seed Database
Run the seeding script to create tables, load products and sales records, perform ABC/XYZ classification, and pre-compute AI forecasts:
```bash
python seed.py
```
> **Default Credentials**:
> - **Username**: `admin`
> - **Password**: `admin123`

### 7. Run Application
```bash
python app.py
```
Open your browser and navigate to: `http://127.0.0.1:5000`

---

## 🧪 Testing
Run the automated authentication test suite:
```bash
python test_auth_audit.py
```

---

## 📄 License
This project is licensed under the MIT License.