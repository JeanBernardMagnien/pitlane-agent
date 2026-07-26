START_REASONS = ('manual', 'agent_restart', 'auto_threshold')
STOP_REASONS = ('manual', 'timeout', 'agent_restart', 'crash', 'auto_threshold')

RISK_LEVELS = ('OK', 'WATCH', 'RISK', 'CRITICAL')
LIMITING_FACTORS = ('cpu_single_core', 'cpu_global', 'ram', 'network', 'disk', 'stability', 'none')

# Seuils non calibrés, à ajuster une fois des données réelles collectées sur le terrain.
CPU_CORE_P95_WATCH = 75.0
CPU_CORE_P95_RISK = 85.0
CPU_CORE_P95_CRITICAL = 95.0

CPU_TOTAL_P95_WATCH = 75.0
CPU_TOTAL_P95_RISK = 85.0
CPU_TOTAL_P95_CRITICAL = 95.0

RAM_AVAILABLE_PERCENT_WATCH = 25.0
RAM_AVAILABLE_PERCENT_RISK = 15.0


_SEVERITY_RANK = {'OK': 0, 'WATCH': 1, 'RISK': 2, 'CRITICAL': 3}
_FACTOR_PRIORITY = ('cpu_single_core', 'ram', 'cpu_global')


def _cpu_core_level(cpu_core_max: float | None) -> str | None:
    if cpu_core_max is None:
        return None
    if cpu_core_max >= CPU_CORE_P95_CRITICAL:
        return 'CRITICAL'
    if cpu_core_max >= CPU_CORE_P95_RISK:
        return 'RISK'
    if cpu_core_max >= CPU_CORE_P95_WATCH:
        return 'WATCH'
    return 'OK'


def _ram_level(ram_available_percent: float | None) -> str | None:
    if ram_available_percent is None:
        return None
    if ram_available_percent < RAM_AVAILABLE_PERCENT_RISK:
        return 'RISK'
    if ram_available_percent < RAM_AVAILABLE_PERCENT_WATCH:
        return 'WATCH'
    return 'OK'


def _cpu_total_level(cpu_total: float | None) -> str | None:
    if cpu_total is None:
        return None
    if cpu_total >= CPU_TOTAL_P95_CRITICAL:
        return 'RISK'
    if cpu_total >= CPU_TOTAL_P95_RISK:
        return 'WATCH'
    return 'OK'


def classify(
    cpu_core_max: float | None,
    cpu_total: float | None,
    ram_available_percent: float | None,
    crash_count: int = 0,
) -> tuple[str, str]:
    """Determine (risk_level, limiting_factor) from aggregate metrics.

    Priorité : stabilité (tout crash) > CPU single-core > RAM > CPU global > aucun facteur.
    Le CPU global ne dépasse jamais RISK ici : un serveur AC EVO est dominé par le
    coût single-core, un CPU global saturé sans cœur individuellement critique reste
    un signal secondaire (voir doctrine capacity_profiler).
    """
    if crash_count and crash_count > 0:
        return 'CRITICAL', 'stability'

    candidates = [
        (factor, level)
        for factor, level in (
            ('cpu_single_core', _cpu_core_level(cpu_core_max)),
            ('ram', _ram_level(ram_available_percent)),
            ('cpu_global', _cpu_total_level(cpu_total)),
        )
        if level is not None
    ]

    if not candidates:
        return 'OK', 'none'

    best_factor, best_level = max(
        candidates,
        key=lambda item: (_SEVERITY_RANK[item[1]], -_FACTOR_PRIORITY.index(item[0])),
    )

    if best_level == 'OK':
        return 'OK', 'none'

    return best_level, best_factor
