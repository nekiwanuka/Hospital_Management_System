from decimal import Decimal, InvalidOperation

from apps.settingsapp.models import SystemSettings


DEFAULT_CONSULTATION_FEE = Decimal("50000.00")
DEFAULT_LAB_FEE = Decimal("30000.00")
DEFAULT_RADIOLOGY_TYPE_RATES = {
    "ultrasound": Decimal("80000.00"),
    "xray": Decimal("60000.00"),
}
DEFAULT_WARD_CATEGORY_RATES = {
    "ordinary": Decimal("50000.00"),
    "vip": Decimal("150000.00"),
    "vvip": Decimal("300000.00"),
}


def _to_decimal(value, fallback):
    if value in (None, ""):
        return fallback
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return fallback


def get_system_settings():
    return SystemSettings.objects.first()


def get_consultation_fee():
    settings_obj = get_system_settings()
    if not settings_obj:
        return DEFAULT_CONSULTATION_FEE
    return _to_decimal(settings_obj.consultation_fee, DEFAULT_CONSULTATION_FEE)


def get_lab_fee(test_type):
    settings_obj = get_system_settings()
    if not settings_obj:
        return DEFAULT_LAB_FEE

    rates = settings_obj.lab_service_rates or {}
    configured = rates.get(test_type)
    return _to_decimal(configured, DEFAULT_LAB_FEE)


def get_radiology_fee(imaging_type, specific_examination=""):
    fallback = DEFAULT_RADIOLOGY_TYPE_RATES.get(imaging_type, Decimal("0.00"))
    settings_obj = get_system_settings()
    if not settings_obj:
        return fallback

    rates = settings_obj.radiology_service_rates or {}
    if specific_examination and specific_examination in rates:
        return _to_decimal(rates.get(specific_examination), fallback)

    return _to_decimal(rates.get(imaging_type), fallback)


def get_ward_category_rate(category):
    """Return the daily rate for a ward category (ordinary / vip / vvip)."""
    fallback = DEFAULT_WARD_CATEGORY_RATES.get(category, Decimal("0.00"))
    settings_obj = get_system_settings()
    if not settings_obj:
        return fallback
    rates = settings_obj.ward_category_rates or {}
    return _to_decimal(rates.get(category), fallback)


def get_all_ward_category_rates():
    """Return dict of all ward category rates."""
    settings_obj = get_system_settings()
    rates = {}
    for cat, _label in [("ordinary", "Ordinary"), ("vip", "VIP"), ("vvip", "VVIP")]:
        fallback = DEFAULT_WARD_CATEGORY_RATES.get(cat, Decimal("0.00"))
        if settings_obj:
            configured = (settings_obj.ward_category_rates or {}).get(cat)
            rates[cat] = _to_decimal(configured, fallback)
        else:
            rates[cat] = fallback
    return rates
