from services.server_manager import get_instance_status


def build_instance_snapshot(instance_cfg: dict) -> dict:
    """Build a runtime snapshot for one configured instance."""
    return get_instance_status(instance_cfg)


def build_instances_snapshot(instances: list[dict]) -> list[dict]:
    """Build runtime snapshots for all configured instances."""
    return [build_instance_snapshot(instance) for instance in instances]
