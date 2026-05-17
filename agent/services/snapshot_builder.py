from services.server_manager import get_instance_status, get_runtime_instances


def build_instance_snapshot(instance_cfg: dict) -> dict:
    """Build a runtime snapshot for one hub-owned instance."""
    return get_instance_status(instance_cfg)


def build_instances_snapshot(instances: list[dict] | None = None) -> list[dict]:
    """Build runtime snapshots for runtime-known instances."""
    runtime_instances = instances if instances is not None else get_runtime_instances()
    return [build_instance_snapshot(instance) for instance in runtime_instances]
