DEFAULT_RUNTIME_POLICY = {
    'stop_on_season_restart': False,
}


def normalize_runtime_policy(payload) -> dict:
    """Valide les garde-fous locaux explicitement décidés par le Hub."""
    if payload is None:
        return dict(DEFAULT_RUNTIME_POLICY)
    if not isinstance(payload, dict):
        raise ValueError('runtime_policy doit être un objet')

    unknown = set(payload) - set(DEFAULT_RUNTIME_POLICY)
    if unknown:
        raise ValueError(f'Option runtime_policy inconnue : {sorted(unknown)[0]}')

    stop_on_season_restart = payload.get('stop_on_season_restart', False)
    if not isinstance(stop_on_season_restart, bool):
        raise ValueError('runtime_policy.stop_on_season_restart doit être un booléen')

    return {
        'stop_on_season_restart': stop_on_season_restart,
    }
