"""Aurora live monitoring (Streamlit dashboard, alerts, drift detectors).

Streamlit is an optional dependency. The pure data/metric helpers in
``dashboard`` work without Streamlit. ``run_dashboard`` requires it and will
raise a clear error when streamlit is missing.
"""

from aurora.monitoring.alerts import (
    Alert,
    AlertConfig,
    AlertEngine,
    AlertRule,
    compute_daily_loss,
    compute_drift_metric,
    compute_max_dd,
    default_rules,
)
from aurora.monitoring.dashboard import (
    DashboardConfig,
    STREAMLIT_AVAILABLE,
    compute_dashboard_metrics,
    fetch_dashboard_data,
    run_dashboard,
)
from aurora.monitoring.drift import (
    ADWINDetector,
    AutoRetrainController,
    KSDriftDetector,
    PageHinkleyDetector,
)

__all__ = [
    "ADWINDetector",
    "Alert",
    "AlertConfig",
    "AlertEngine",
    "AlertRule",
    "AutoRetrainController",
    "DashboardConfig",
    "KSDriftDetector",
    "PageHinkleyDetector",
    "STREAMLIT_AVAILABLE",
    "compute_daily_loss",
    "compute_dashboard_metrics",
    "compute_drift_metric",
    "compute_max_dd",
    "default_rules",
    "fetch_dashboard_data",
    "run_dashboard",
]
