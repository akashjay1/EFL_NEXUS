from kpi_profile import load_saved_profile


def identity(config_path, hostname):
    profile = load_saved_profile(config_path)
    return {'operator_name': profile[0] if profile else hostname,
            'identity_source': 'KPI Profile' if profile else 'Device Fallback'}
