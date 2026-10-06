"""
PatchTST (Patch Time Series Transformer) Demand Forecasting Module.

Implements a proper time-series forecasting pipeline:
  1. Date-indexed daily series construction (fills gaps, handles duplicates)
  2. Sliding-window training with actual future targets
  3. Chronological train/validation split
  4. Validation metrics (MAE, RMSE, MAPE)
  5. Confidence intervals from validation residuals
  6. Statistical fallback for products with limited history
  7. All dates via IST-aware utility
"""

import os
import math
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from utils.date_utils import get_current_date_ist, get_forecast_target_date

# Try importing torch; fallback if not available
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

# ---------------------------------------------------------------------------
# Minimum data requirements
# ---------------------------------------------------------------------------
MIN_DAYS_PATCHTST = 24     # Need context_length + model_horizon + a few windows
MIN_DAYS_STATISTICAL = 7   # Need at least 1 week for statistical fallback
CONTEXT_LENGTH = 14        # Lookback window for model input (2 weeks)
MODEL_HORIZON = 7          # Train model to predict 7 days; extrapolate for 15/30
MAX_FORECAST_HORIZON = 30  # Maximum prediction horizon


# ===========================================================================
# Data Preparation
# ===========================================================================

def prepare_daily_series(sales_records) -> pd.DataFrame:
    """
    Converts raw Sale records into a clean date-indexed daily time series.

    Returns DataFrame with columns: ['date', 'quantity']
    - Sorted by date ascending
    - Duplicate dates aggregated (summed)
    - Missing dates filled with 0 (zero sales, NOT missing data)
    - No future dates included
    """
    if not sales_records:
        return pd.DataFrame(columns=['date', 'quantity'])

    data = []
    for s in sales_records:
        sale_date = s.sale_date
        if isinstance(sale_date, str):
            sale_date = datetime.strptime(sale_date, '%Y-%m-%d').date()
        data.append({'date': sale_date, 'quantity': int(s.quantity_sold)})

    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date'])

    # Aggregate duplicate dates
    df = df.groupby('date', as_index=False)['quantity'].sum()

    # Sort chronologically
    df = df.sort_values('date').reset_index(drop=True)

    # Fill missing dates with 0 (zero-sale days are valid data points)
    if len(df) >= 2:
        full_range = pd.date_range(start=df['date'].min(), end=df['date'].max(), freq='D')
        df = df.set_index('date').reindex(full_range, fill_value=0).reset_index()
        df.columns = ['date', 'quantity']

    # Ensure non-negative
    df['quantity'] = df['quantity'].clip(lower=0)

    return df


# ===========================================================================
# PatchTST PyTorch Model
# ===========================================================================

class TorchPatchTST(nn.Module):
    """
    PatchTST Transformer model for time-series forecasting.

    Architecture:
      Input (context_length,) → Patch Embedding → Positional Encoding
      → Transformer Encoder (multi-head self-attention) → Mean Pooling
      → Linear Head → (forecast_horizon,) daily predictions
    """

    def __init__(self, context_length, forecast_horizon, patch_len=7, stride=4,
                 d_model=32, n_heads=4, d_ff=64, num_layers=2, dropout=0.1):
        super().__init__()
        self.context_length = context_length
        self.forecast_horizon = forecast_horizon
        self.patch_len = patch_len
        self.stride = stride

        # Calculate number of patches
        self.num_patches = max(1, (context_length - patch_len) // stride + 1)

        # Patch embedding
        self.patch_embed = nn.Linear(patch_len, d_model)
        self.pos_encoder = nn.Parameter(torch.randn(1, self.num_patches, d_model) * 0.02)

        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_ff,
            dropout=dropout, batch_first=True, activation='gelu'
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

        # Prediction head: outputs daily forecasts
        self.head = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_ff, forecast_horizon)
        )

    def _create_patches(self, x):
        """Create patches from input sequence. x shape: [batch, context_length]"""
        batch_size = x.shape[0]
        patches = []
        for i in range(self.num_patches):
            start = i * self.stride
            end = start + self.patch_len
            if end <= x.shape[1]:
                patches.append(x[:, start:end])
            else:
                # Pad last patch if needed
                pad_size = end - x.shape[1]
                patch = torch.cat([x[:, start:], x[:, -1:].expand(batch_size, pad_size)], dim=1)
                patches.append(patch)
        return torch.stack(patches, dim=1)  # [batch, num_patches, patch_len]

    def forward(self, x):
        """x shape: [batch, context_length] → output: [batch, forecast_horizon]"""
        patches = self._create_patches(x)                    # [B, num_patches, patch_len]
        embeddings = self.patch_embed(patches)                # [B, num_patches, d_model]
        embeddings = embeddings + self.pos_encoder[:, :self.num_patches, :]
        encoded = self.transformer_encoder(embeddings)        # [B, num_patches, d_model]
        pooled = encoded.mean(dim=1)                          # [B, d_model]
        output = self.head(pooled)                            # [B, forecast_horizon]
        return output


# ===========================================================================
# Training Pipeline
# ===========================================================================

def create_sliding_windows(series_values, context_length, forecast_horizon):
    """
    Creates sliding window (input, target) pairs from a 1D array.

    Each window: input = series[i : i+context_length]
                 target = series[i+context_length : i+context_length+forecast_horizon]

    Returns: X (N, context_length), Y (N, forecast_horizon)
    """
    X, Y = [], []
    total = len(series_values)
    for i in range(total - context_length - forecast_horizon + 1):
        X.append(series_values[i: i + context_length])
        Y.append(series_values[i + context_length: i + context_length + forecast_horizon])
    if len(X) == 0:
        return np.array([]).reshape(0, context_length), np.array([]).reshape(0, forecast_horizon)
    return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32)


def compute_metrics(y_true, y_pred):
    """Computes MAE, RMSE, and MAPE for forecast evaluation."""
    y_true = np.array(y_true, dtype=np.float64)
    y_pred = np.array(y_pred, dtype=np.float64)

    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

    # MAPE with safety for zero values
    mask = y_true > 0
    if mask.sum() > 0:
        mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)
    else:
        mape = None  # Cannot compute MAPE when actuals are all zero

    return {'mae': round(mae, 4), 'rmse': round(rmse, 4), 'mape': round(mape, 2) if mape is not None else None}


# ===========================================================================
# PatchTST Forecasting Engine
# ===========================================================================

class PatchTSTForecaster:
    """
    Complete PatchTST forecasting pipeline with:
    - Proper sliding-window training
    - Time-series cross-validation
    - Statistical fallback for limited data
    - Confidence intervals from residuals
    """

    def __init__(self, context_length=CONTEXT_LENGTH, patch_len=7, stride=4,
                 d_model=32, n_heads=4, d_ff=64, num_layers=2, dropout=0.1,
                 lr=0.001, epochs=100, patience=15, batch_size=8):
        self.context_length = context_length
        self.patch_len = patch_len
        self.stride = stride
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_ff = d_ff
        self.num_layers = num_layers
        self.dropout = dropout
        self.lr = lr
        self.epochs = epochs
        self.patience = patience
        self.batch_size = batch_size

    def forecast(self, daily_series: pd.DataFrame, horizons=[7, 15, 30]):
        """
        Main entry point. Takes a clean daily DataFrame and returns forecasts.

        Args:
            daily_series: DataFrame with ['date', 'quantity'] columns
            horizons: list of forecast horizons in days

        Returns:
            dict with keys for each horizon, plus 'metrics' and 'meta' info
        """
        n_days = len(daily_series)
        values = daily_series['quantity'].values.astype(np.float32)

        # Determine last historical date
        if n_days > 0:
            last_hist_date = daily_series['date'].iloc[-1]
            if isinstance(last_hist_date, pd.Timestamp):
                last_hist_date = last_hist_date.date()
        else:
            last_hist_date = None

        max_horizon = max(horizons)

        # ---------------------------------------------------------------
        # Case 1: Insufficient data — cannot forecast reliably
        # ---------------------------------------------------------------
        if n_days < MIN_DAYS_STATISTICAL:
            return self._insufficient_data_result(values, horizons, last_hist_date)

        # ---------------------------------------------------------------
        # Case 2: Limited data — use statistical fallback
        # ---------------------------------------------------------------
        if n_days < MIN_DAYS_PATCHTST or not HAS_TORCH:
            return self._statistical_forecast(values, horizons, last_hist_date)

        # ---------------------------------------------------------------
        # Case 3: Sufficient data — use PatchTST
        # ---------------------------------------------------------------
        return self._patchtst_forecast(values, horizons, last_hist_date)

    # -------------------------------------------------------------------
    # Case 1: Insufficient Data
    # -------------------------------------------------------------------
    def _insufficient_data_result(self, values, horizons, last_hist_date):
        """Returns baseline estimates with low confidence when data is very limited."""
        if len(values) > 0:
            daily_avg = float(np.mean(values))
            daily_std = float(np.std(values)) if len(values) > 1 else daily_avg * 0.5
        else:
            daily_avg = 0.0
            daily_std = 0.0

        # Explanation for insufficient data
        explanation_summary = (
            f"Limited to {len(values)} day(s) of sales data — forecast is based on a "
            f"simple daily average of {daily_avg:.1f} units. More history is needed for "
            f"reliable predictions."
        )
        top_factors = json.dumps([
            {"factor": "Insufficient sales history", "impact_percent": 100.0}
        ])

        # Calculate simple 14-day moving average baseline
        baseline_14d = values[-min(len(values), 14):] if len(values) > 0 else np.array([0.0])
        baseline_daily_rate = float(np.mean(baseline_14d))

        results = {}
        ref_date = last_hist_date or get_current_date_ist()

        for h in horizons:
            pred = max(0, round(daily_avg * h, 1))
            spread = max(1.0, daily_std * math.sqrt(h) * 2.0)
            results[h] = {
                'predicted_demand': pred,
                'confidence_lower': round(max(0, pred - spread), 1),
                'confidence_upper': round(pred + spread, 1),
                'forecast_date': get_forecast_target_date(h, ref_date),
                'explanation_summary': explanation_summary,
                'top_factors': top_factors,
                'baseline_predicted_demand': round(max(0.0, baseline_daily_rate * h), 1),
                'baseline_method': '14-Day Moving Average',
                'baseline_mae': None,
                'baseline_rmse': None,
            }

        results['meta'] = {
            'method': 'Insufficient Data',
            'data_confidence': 'Low',
            'n_days': len(values),
            'last_historical_date': last_hist_date,
            'generation_date': ref_date,
            'message': f'Only {len(values)} day(s) of sales history available. At least {MIN_DAYS_STATISTICAL} days needed for basic forecasting.'
        }
        results['metrics'] = {'mae': None, 'rmse': None, 'mape': None}
        return results

    # -------------------------------------------------------------------
    # Case 2: Statistical Fallback (Weighted Moving Average + Trend)
    # -------------------------------------------------------------------
    def _statistical_forecast(self, values, horizons, last_hist_date):
        """Uses weighted moving average with trend for limited-data products."""
        n = len(values)
        ref_date = last_hist_date or get_current_date_ist()

        # Weighted moving average (recent data weighted more)
        weights = np.linspace(0.5, 1.0, n)
        weighted_avg = float(np.average(values, weights=weights))

        # Trend detection
        if n >= 14:
            recent_mean = np.mean(values[-7:])
            earlier_mean = np.mean(values[-14:-7])
            trend_factor = (recent_mean - earlier_mean) / (earlier_mean + 1e-5)
            trend_factor = np.clip(trend_factor, -0.3, 0.3)  # Cap extreme trends
        elif n >= 7:
            half = n // 2
            recent_mean = np.mean(values[half:])
            earlier_mean = np.mean(values[:half])
            trend_factor = (recent_mean - earlier_mean) / (earlier_mean + 1e-5)
            trend_factor = np.clip(trend_factor, -0.3, 0.3)
        else:
            trend_factor = 0.0
            recent_mean = float(np.mean(values))
            earlier_mean = recent_mean

        daily_rate = weighted_avg * (1 + trend_factor)
        daily_rate = max(0, daily_rate)

        std_dev = float(np.std(values)) if n > 1 else daily_rate * 0.3
        historical_max_daily = float(np.max(values))

        # Validation: use last 7 days as validation
        val_metrics = {'mae': None, 'rmse': None, 'mape': None}
        baseline_val_metrics = {'mae': None, 'rmse': None, 'mape': None}
        if n >= 14:
            val_actual = values[-7:]
            val_pred = np.full(7, daily_rate)
            val_metrics = compute_metrics(val_actual, val_pred)

            # Baseline validation: 14-day simple moving average prior to validation window
            prior_14d = values[max(0, n - 21): n - 7]
            baseline_val_rate = float(np.mean(prior_14d)) if len(prior_14d) > 0 else float(np.mean(values[: n - 7]))
            baseline_val_pred = np.full(7, baseline_val_rate)
            baseline_val_metrics = compute_metrics(val_actual, baseline_val_pred)

        # Baseline prediction for forecast period
        baseline_14d = values[-min(n, 14):] if n > 0 else np.array([0.0])
        baseline_daily_rate = float(np.mean(baseline_14d))

        # --- Generate rule-based explanation ---
        explanation_summary, top_factors = self._generate_statistical_explanation(
            values, n, trend_factor, recent_mean, earlier_mean
        )

        results = {}
        for h in horizons:
            pred = round(daily_rate * h, 1)
            # Cap at 3x historical max daily rate * horizon
            max_reasonable = historical_max_daily * 3.0 * h
            pred = min(pred, max_reasonable)
            pred = max(0, pred)

            # Confidence intervals widen with horizon
            ci_multiplier = 1.96 * std_dev * math.sqrt(h)
            lower = round(max(0, pred - ci_multiplier), 1)
            upper = round(pred + ci_multiplier, 1)

            results[h] = {
                'predicted_demand': pred,
                'confidence_lower': lower,
                'confidence_upper': upper,
                'forecast_date': get_forecast_target_date(h, ref_date),
                'explanation_summary': explanation_summary,
                'top_factors': top_factors,
                'baseline_predicted_demand': round(max(0.0, baseline_daily_rate * h), 1),
                'baseline_method': '14-Day Moving Average',
                'baseline_mae': baseline_val_metrics.get('mae'),
                'baseline_rmse': baseline_val_metrics.get('rmse'),
            }

        # Determine confidence level
        data_confidence = 'Medium' if n >= 14 else 'Low'

        results['meta'] = {
            'method': 'Statistical Fallback',
            'data_confidence': data_confidence,
            'n_days': n,
            'last_historical_date': last_hist_date,
            'generation_date': ref_date,
            'message': f'{n} days of history used. Statistical weighted moving average with trend applied.'
        }
        results['metrics'] = val_metrics
        return results

    def _generate_statistical_explanation(self, values, n, trend_factor, recent_mean, earlier_mean):
        """Generates a rule-based explanation for the statistical fallback forecast."""
        factors = []
        parts = []

        # Trend analysis
        trend_pct = round(float(trend_factor) * 100, 1)
        if trend_pct > 5:
            parts.append(f"Recent upward sales trend was the biggest factor (+{trend_pct}%)")
            factors.append({"factor": "Upward sales trend", "impact_percent": abs(trend_pct)})
        elif trend_pct < -5:
            parts.append(f"Recent downward sales trend was the biggest factor ({trend_pct}%)")
            factors.append({"factor": "Downward sales trend", "impact_percent": abs(trend_pct)})
        else:
            parts.append("Sales have been relatively stable recently")
            factors.append({"factor": "Stable sales pattern", "impact_percent": abs(trend_pct)})

        # Weekday vs weekend seasonality detection
        if n >= 7:
            # Reconstruct day-of-week pattern from available data
            weekday_vals = []
            weekend_vals = []
            for i, v in enumerate(values[-min(n, 14):]):
                # Approximate: index modulo 7 gives pseudo-day-of-week
                if i % 7 in [5, 6]:  # Approximate weekend positions
                    weekend_vals.append(v)
                else:
                    weekday_vals.append(v)

            if weekday_vals and weekend_vals:
                wkday_avg = float(np.mean(weekday_vals))
                wkend_avg = float(np.mean(weekend_vals))
                if wkday_avg > 0:
                    seasonality_pct = round(((wkend_avg - wkday_avg) / wkday_avg) * 100, 1)
                    if abs(seasonality_pct) > 10:
                        if seasonality_pct > 0:
                            parts.append(f"followed by weekend spike pattern (+{seasonality_pct}%)")
                            factors.append({"factor": "Weekend spike pattern", "impact_percent": abs(seasonality_pct)})
                        else:
                            parts.append(f"with lower weekend sales ({seasonality_pct}%)")
                            factors.append({"factor": "Lower weekend sales", "impact_percent": abs(seasonality_pct)})

        # Data volume note
        if n < 14:
            parts.append(f"Note: only {n} days of data available, limiting forecast accuracy")
            factors.append({"factor": "Limited data history", "impact_percent": round(max(0, (14 - n) / 14 * 30), 1)})

        explanation_summary = ", ".join(parts) + "."
        top_factors = json.dumps(factors[:3])
        return explanation_summary, top_factors

    # -------------------------------------------------------------------
    # Case 3: PatchTST Deep Learning Forecast
    # -------------------------------------------------------------------
    def _patchtst_forecast(self, values, horizons, last_hist_date):
        """Full PatchTST transformer forecast with proper training.
        
        Strategy: Train the model to predict MODEL_HORIZON (7) days ahead.
        This gives many more sliding windows from limited data.
        Then extrapolate for 15 and 30 days using the learned daily rate.
        """
        n = len(values)
        today = last_hist_date or get_current_date_ist()
        model_horizon = MODEL_HORIZON  # Train on 7-day predictions

        # Normalization (min-max scaling to [0, 1])
        val_min = float(np.min(values))
        val_max = float(np.max(values))
        val_range = val_max - val_min if val_max > val_min else 1.0
        normalized = (values - val_min) / val_range

        # Create sliding windows for model_horizon (7 days)
        X_all, Y_all = create_sliding_windows(normalized, self.context_length, model_horizon)

        if len(X_all) < 3:
            # Not enough windows — fall back to statistical
            return self._statistical_forecast(values, horizons, last_hist_date)

        # Time-series split: last window(s) for validation, rest for training
        val_size = max(1, min(len(X_all) // 4, 3))  # 25% or max 3 windows
        X_train, Y_train = X_all[:-val_size], Y_all[:-val_size]
        X_val, Y_val = X_all[-val_size:], Y_all[-val_size:]

        if len(X_train) < 2:
            # Still not enough training windows
            return self._statistical_forecast(values, horizons, last_hist_date)

        try:
            # Build model
            model = TorchPatchTST(
                context_length=self.context_length,
                forecast_horizon=model_horizon,
                patch_len=self.patch_len,
                stride=self.stride,
                d_model=self.d_model,
                n_heads=self.n_heads,
                d_ff=self.d_ff,
                num_layers=self.num_layers,
                dropout=self.dropout
            )

            optimizer = optim.Adam(model.parameters(), lr=self.lr, weight_decay=1e-5)
            scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=5)
            criterion = nn.MSELoss()

            X_train_t = torch.tensor(X_train, dtype=torch.float32)
            Y_train_t = torch.tensor(Y_train, dtype=torch.float32)
            X_val_t = torch.tensor(X_val, dtype=torch.float32)
            Y_val_t = torch.tensor(Y_val, dtype=torch.float32)

            # Training loop with early stopping
            best_val_loss = float('inf')
            patience_counter = 0
            best_state = None

            model.train()
            for epoch in range(self.epochs):
                # Mini-batch training
                indices = torch.randperm(len(X_train_t))
                epoch_loss = 0.0
                n_batches = 0

                for start_idx in range(0, len(X_train_t), self.batch_size):
                    batch_idx = indices[start_idx:start_idx + self.batch_size]
                    x_batch = X_train_t[batch_idx]
                    y_batch = Y_train_t[batch_idx]

                    optimizer.zero_grad()
                    preds = model(x_batch)
                    loss = criterion(preds, y_batch)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                    optimizer.step()
                    epoch_loss += loss.item()
                    n_batches += 1

                avg_train_loss = epoch_loss / max(n_batches, 1)

                # Validation
                model.eval()
                with torch.no_grad():
                    val_preds = model(X_val_t)
                    val_loss = criterion(val_preds, Y_val_t).item()
                model.train()

                scheduler.step(val_loss)

                # Early stopping
                if val_loss < best_val_loss - 1e-6:
                    best_val_loss = val_loss
                    patience_counter = 0
                    best_state = {k: v.clone() for k, v in model.state_dict().items()}
                else:
                    patience_counter += 1
                    if patience_counter >= self.patience:
                        break

            # Load best model
            if best_state is not None:
                model.load_state_dict(best_state)

            # ------- Inference -------
            model.eval()

            # Use the last context_length values for prediction
            last_context = normalized[-self.context_length:]
            last_context_t = torch.tensor(last_context, dtype=torch.float32).unsqueeze(0)

            with torch.no_grad():
                pred_normalized = model(last_context_t).squeeze(0).numpy()

            # Inverse normalization: these are the next 7 days of daily predictions
            pred_daily_7d = pred_normalized * val_range + val_min
            pred_daily_7d = np.clip(pred_daily_7d, 0, None)  # Non-negative demand

            # Cap extreme outliers
            max_reasonable_daily = float(np.max(values)) * 3.0
            pred_daily_7d = np.clip(pred_daily_7d, 0, max_reasonable_daily)

            # Compute daily rate from the 7-day prediction for extrapolation
            pred_daily_rate = float(np.mean(pred_daily_7d))

            # ------- Validation Metrics (on denormalized values) -------
            with torch.no_grad():
                val_pred_norm = model(X_val_t).numpy()

            val_pred_denorm = val_pred_norm * val_range + val_min
            val_actual_denorm = Y_val * val_range + val_min

            # Compute aggregate metrics across all validation windows
            all_actual = val_actual_denorm.flatten()
            all_pred = val_pred_denorm.flatten()
            overall_metrics = compute_metrics(all_actual, all_pred)

            # ------- Baseline Validation Metrics (14-day simple moving average) -------
            # For each validation window, baseline prediction is the 14-day mean of that window
            X_val_denorm = X_val * val_range + val_min
            baseline_window_means = np.mean(X_val_denorm, axis=1, keepdims=True)  # (val_size, 1)
            baseline_val_pred_denorm = np.repeat(baseline_window_means, model_horizon, axis=1)  # (val_size, 7)
            all_baseline_pred = baseline_val_pred_denorm.flatten()
            baseline_metrics = compute_metrics(all_actual, all_baseline_pred)

            # Baseline prediction for future horizons (14-day simple average of recent days)
            baseline_14d = values[-min(n, 14):] if n > 0 else np.array([0.0])
            baseline_daily_rate = float(np.mean(baseline_14d))

            # ------- Confidence intervals from validation residuals -------
            residuals = all_actual - all_pred
            residual_std = float(np.std(residuals)) if len(residuals) > 1 else float(np.std(values)) * 0.2

            # ------- Generate SHAP-based explanation -------
            explanation_summary, top_factors = self._generate_patchtst_explanation(
                model, values, normalized, val_range, val_min,
                pred_daily_7d, X_all
            )

            # ------- Build results for each horizon -------
            results = {}
            for h in horizons:
                if h <= model_horizon:
                    # Direct sum of model's daily predictions
                    pred_sum = float(np.sum(pred_daily_7d[:h]))
                else:
                    # Use model's 7-day prediction + extrapolate remaining days
                    pred_7d_sum = float(np.sum(pred_daily_7d))
                    remaining_days = h - model_horizon
                    pred_sum = pred_7d_sum + (pred_daily_rate * remaining_days)

                pred_sum = round(max(0, pred_sum), 1)

                # Confidence interval widens with horizon
                ci_spread = 1.96 * residual_std * math.sqrt(h)
                lower = round(max(0, pred_sum - ci_spread), 1)
                upper = round(pred_sum + ci_spread, 1)

                results[h] = {
                    'predicted_demand': pred_sum,
                    'confidence_lower': lower,
                    'confidence_upper': upper,
                    'forecast_date': get_forecast_target_date(h, today),
                    'explanation_summary': explanation_summary,
                    'top_factors': top_factors,
                    'baseline_predicted_demand': round(max(0.0, baseline_daily_rate * h), 1),
                    'baseline_method': '14-Day Moving Average',
                    'baseline_mae': baseline_metrics.get('mae'),
                    'baseline_rmse': baseline_metrics.get('rmse'),
                }

            # Determine confidence level based on metrics, data size, and horizon
            data_confidence = 'High'
            if overall_metrics['mae'] is not None:
                # For aggregate forecast, sum-level error matters more than daily error
                # Aggregate MAE over 7 days: MAE * sqrt(7) roughly (errors partially cancel)
                # Compare to aggregate actual demand over 7 days
                mean_actual_7d = float(np.mean(np.abs(all_actual))) * model_horizon
                aggregate_mae_7d = overall_metrics['mae'] * math.sqrt(model_horizon)
                relative_error = aggregate_mae_7d / (mean_actual_7d + 1e-5)
                if relative_error > 0.4:
                    data_confidence = 'Low'
                elif relative_error > 0.2:
                    data_confidence = 'Medium'

            # Factor in data quantity
            if n < 21:
                data_confidence = 'Low'
            elif n < 35 and data_confidence == 'High':
                data_confidence = 'Medium'

            results['meta'] = {
                'method': 'PatchTST',
                'data_confidence': data_confidence,
                'n_days': n,
                'last_historical_date': last_hist_date,
                'generation_date': today,
                'training_windows': len(X_train),
                'validation_windows': len(X_val),
                'message': f'PatchTST Transformer trained on {n} days of history with {len(X_train)} training windows.'
            }
            results['metrics'] = overall_metrics
            return results

        except Exception as e:
            print(f"[PatchTST] PyTorch execution error: {e}. Falling back to statistical method.")
            return self._statistical_forecast(values, horizons, last_hist_date)

    def _generate_patchtst_explanation(self, model, values, normalized, val_range, val_min,
                                        pred_daily_7d, X_all):
        """
        Generates a SHAP-based explanation for the PatchTST forecast.

        Uses SHAP KernelExplainer with the trained model wrapped as a numpy callable.
        Falls back to rule-based explanation if SHAP fails for any reason.
        """
        try:
            import shap

            # Wrap the PyTorch model as a numpy function for SHAP
            def model_predict_fn(X_np):
                """Takes numpy context windows, returns sum of 7-day predictions."""
                X_t = torch.tensor(X_np, dtype=torch.float32)
                model.eval()
                with torch.no_grad():
                    preds = model(X_t).numpy()
                # Denormalize and sum to get total demand over 7 days
                preds_denorm = preds * val_range + val_min
                preds_denorm = np.clip(preds_denorm, 0, None)
                return preds_denorm.sum(axis=1)  # shape: (batch,)

            # Use a small background sample for speed (up to 10 windows)
            n_bg = min(len(X_all), 10)
            bg_indices = np.linspace(0, len(X_all) - 1, n_bg, dtype=int)
            background = X_all[bg_indices]

            # The instance to explain: the last context window
            instance = normalized[-self.context_length:].reshape(1, -1)

            explainer = shap.KernelExplainer(model_predict_fn, background)
            shap_values = explainer.shap_values(instance, nsamples=50)

            if isinstance(shap_values, list):
                sv = shap_values[0]
            else:
                sv = shap_values[0] if shap_values.ndim > 1 else shap_values

            # Group SHAP values by patch regions
            ctx_len = self.context_length
            patch_len = self.patch_len
            stride = self.stride
            num_patches = max(1, (ctx_len - patch_len) // stride + 1)

            patch_importances = []
            for p_idx in range(num_patches):
                start = p_idx * stride
                end = min(start + patch_len, ctx_len)
                patch_shap = float(np.sum(np.abs(sv[start:end])))
                days_ago_start = ctx_len - start
                days_ago_end = ctx_len - end
                patch_importances.append({
                    'patch_idx': p_idx,
                    'shap_total': patch_shap,
                    'days_ago_start': days_ago_start,
                    'days_ago_end': max(0, days_ago_end),
                    'mean_value': float(np.mean(values[-(days_ago_start):-(days_ago_end) if days_ago_end > 0 else None])),
                    'shap_sign': float(np.sum(sv[start:end]))
                })

            # Sort by importance
            patch_importances.sort(key=lambda x: x['shap_total'], reverse=True)
            total_shap = sum(pi['shap_total'] for pi in patch_importances) or 1.0

            # Translate top 3 patches into plain language
            factors = []
            parts = []
            for pi in patch_importances[:3]:
                impact_pct = round((pi['shap_total'] / total_shap) * 100, 1)
                if impact_pct < 5:
                    continue

                if pi['days_ago_end'] <= 3:
                    # Most recent days
                    if pi['shap_sign'] > 0:
                        label = "Recent upward sales trend"
                    else:
                        label = "Recent sales slowdown"
                elif pi['days_ago_start'] <= 7:
                    # Within last week — check weekend overlap
                    label = "Last week's sales pattern"
                else:
                    label = "Historical baseline sales level"

                sign = "+" if pi['shap_sign'] >= 0 else "-"
                parts.append(f"{label} was a key factor ({sign}{impact_pct}%)")
                factors.append({"factor": label, "impact_percent": impact_pct})

            if parts:
                explanation_summary = ", ".join(parts) + "."
            else:
                explanation_summary = "The PatchTST model used recent sales patterns to generate this forecast."
                factors = [{"factor": "Recent sales patterns", "impact_percent": 100.0}]

            top_factors = json.dumps(factors[:3])
            return explanation_summary, top_factors

        except Exception as e:
            print(f"[PatchTST] SHAP explanation failed ({e}), falling back to rule-based explanation.")
            # Fall back to rule-based explanation using the raw values
            return self._generate_patchtst_rule_explanation(values, pred_daily_7d)

    def _generate_patchtst_rule_explanation(self, values, pred_daily_7d):
        """Rule-based fallback explanation when SHAP fails on PatchTST."""
        n = len(values)
        factors = []
        parts = []

        # Trend
        if n >= 14:
            recent_mean = float(np.mean(values[-7:]))
            earlier_mean = float(np.mean(values[-14:-7]))
            trend_pct = round(((recent_mean - earlier_mean) / (earlier_mean + 1e-5)) * 100, 1)
        elif n >= 7:
            half = n // 2
            recent_mean = float(np.mean(values[half:]))
            earlier_mean = float(np.mean(values[:half]))
            trend_pct = round(((recent_mean - earlier_mean) / (earlier_mean + 1e-5)) * 100, 1)
        else:
            trend_pct = 0.0

        if trend_pct > 5:
            parts.append(f"Recent upward sales trend (+{trend_pct}%)")
            factors.append({"factor": "Upward sales trend", "impact_percent": abs(trend_pct)})
        elif trend_pct < -5:
            parts.append(f"Recent downward sales trend ({trend_pct}%)")
            factors.append({"factor": "Downward sales trend", "impact_percent": abs(trend_pct)})
        else:
            parts.append("Sales have been relatively stable")
            factors.append({"factor": "Stable sales pattern", "impact_percent": abs(trend_pct)})

        # Predicted rate vs historical average
        pred_avg = float(np.mean(pred_daily_7d))
        hist_avg = float(np.mean(values[-7:])) if n >= 7 else float(np.mean(values))
        if hist_avg > 0:
            pred_diff_pct = round(((pred_avg - hist_avg) / hist_avg) * 100, 1)
            if abs(pred_diff_pct) > 5:
                direction = "higher" if pred_diff_pct > 0 else "lower"
                parts.append(f"model predicts {direction} daily demand than recent average ({pred_diff_pct:+.1f}%)")
                factors.append({"factor": f"Predicted demand {direction} than average", "impact_percent": abs(pred_diff_pct)})

        explanation_summary = ", ".join(parts) + "." if parts else "PatchTST model used recent sales patterns."
        top_factors = json.dumps(factors[:3])
        return explanation_summary, top_factors


# ===========================================================================
# Public API: Train and Forecast for a Product
# ===========================================================================

def train_and_forecast_product(db_session, product_id):
    """
    Runs the PatchTST demand forecast pipeline for a single product.

    Steps:
      1. Loads product and its sales history from the database
      2. Prepares a clean daily time series
      3. Runs the forecaster (PatchTST or fallback)
      4. Saves predictions to ForecastPrediction table
      5. Returns saved prediction objects

    All dates are calculated using IST (Asia/Kolkata).
    """
    from models import Product, Sale, ForecastPrediction

    product = db_session.query(Product).get(product_id)
    if not product:
        return None

    # Fetch historical sales sorted by date
    sales_records = (
        db_session.query(Sale)
        .filter_by(product_id=product_id)
        .order_by(Sale.sale_date.asc())
        .all()
    )

    # Prepare clean daily series
    daily_series = prepare_daily_series(sales_records)

    # Run forecaster
    forecaster = PatchTSTForecaster()
    forecasts = forecaster.forecast(daily_series, horizons=[7, 15, 30])

    # Extract metadata
    meta = forecasts.get('meta', {})
    metrics = forecasts.get('metrics', {})
    today = meta.get('generation_date') or get_current_date_ist()

    # Clear old predictions for this product
    db_session.query(ForecastPrediction).filter_by(product_id=product_id).delete()

    saved_predictions = []
    for horizon in [7, 15, 30]:
        if horizon not in forecasts:
            continue
        f_data = forecasts[horizon]

        pred_obj = ForecastPrediction(
            product_id=product_id,
            forecast_date=f_data['forecast_date'],
            horizon_days=horizon,
            predicted_demand=f_data['predicted_demand'],
            confidence_lower=f_data['confidence_lower'],
            confidence_upper=f_data['confidence_upper'],
            forecast_generation_date=meta.get('generation_date', today),
            last_historical_date=meta.get('last_historical_date'),
            model_method=meta.get('method', 'PatchTST'),
            model_mae=metrics.get('mae'),
            model_rmse=metrics.get('rmse'),
            data_confidence=meta.get('data_confidence', 'Medium'),
            explanation_summary=f_data.get('explanation_summary'),
            top_factors=f_data.get('top_factors'),
            baseline_predicted_demand=f_data.get('baseline_predicted_demand'),
            baseline_method=f_data.get('baseline_method', '14-Day Moving Average'),
            baseline_mae=f_data.get('baseline_mae'),
            baseline_rmse=f_data.get('baseline_rmse'),
        )
        db_session.add(pred_obj)
        saved_predictions.append(pred_obj)

    db_session.commit()
    return saved_predictions


def get_baseline_comparison_summary(db_session):
    """
    Returns a dict summarizing how much better the AI model performs vs. the
    simple baseline, averaged across all products that have both MAE values.
    e.g. {"average_improvement_percent": 23.4, "products_compared": 87}
    """
    from models import ForecastPrediction, Product

    # Select unique products that have both model_mae and baseline_mae (take horizon 7d which represents training run)
    preds = (
        db_session.query(ForecastPrediction)
        .filter(
            ForecastPrediction.model_mae.isnot(None),
            ForecastPrediction.baseline_mae.isnot(None),
            ForecastPrediction.baseline_mae > 0,
            ForecastPrediction.horizon_days == 7
        )
        .all()
    )

    if not preds:
        # Fallback if horizon 7 is not present
        preds = (
            db_session.query(ForecastPrediction)
            .filter(
                ForecastPrediction.model_mae.isnot(None),
                ForecastPrediction.baseline_mae.isnot(None),
                ForecastPrediction.baseline_mae > 0
            )
            .all()
        )
        # Deduplicate by product_id
        seen_products = set()
        unique_preds = []
        for p in preds:
            if p.product_id not in seen_products:
                seen_products.add(p.product_id)
                unique_preds.append(p)
        preds = unique_preds

    if not preds:
        return {
            "average_improvement_percent": 0.0,
            "products_compared": 0,
            "avg_model_mae": None,
            "avg_baseline_mae": None,
        }

    improvements = []
    model_maes = []
    baseline_maes = []

    for p in preds:
        b_mae = float(p.baseline_mae)
        m_mae = float(p.model_mae)
        if b_mae > 0:
            imp = ((b_mae - m_mae) / b_mae) * 100.0
            improvements.append(imp)
            model_maes.append(m_mae)
            baseline_maes.append(b_mae)

    avg_improvement = round(float(np.mean(improvements)), 1) if improvements else 0.0
    avg_model_mae = round(float(np.mean(model_maes)), 2) if model_maes else None
    avg_baseline_mae = round(float(np.mean(baseline_maes)), 2) if baseline_maes else None

    return {
        "average_improvement_percent": avg_improvement,
        "products_compared": len(improvements),
        "avg_model_mae": avg_model_mae,
        "avg_baseline_mae": avg_baseline_mae,
    }
