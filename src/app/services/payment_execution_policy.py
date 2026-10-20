"""Shared deployment switch checked at both HTTP and provider effect boundaries."""
import os


class PaymentExecutionDisabled(RuntimeError):
    """The shared deployment policy denied a provider effect."""


def payment_execution_enabled(app_env=None):
    explicit=str(os.getenv('PAYMENT_EXECUTION_ENABLED','') or '').strip().lower()
    if explicit in ('1','true','yes','on'):return True
    if explicit in ('0','false','no','off'):return False
    if explicit:
        return False
    environment = 'local' if app_env is None else str(app_env).strip().lower()
    return environment in ('local','dev','development','test','testing')


def require_payment_execution():
    from src.app.config import get_settings
    if not payment_execution_enabled(getattr(get_settings(),'app_env',None)):
        raise PaymentExecutionDisabled('payment_execution_disabled')
