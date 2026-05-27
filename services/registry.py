_REGISTRY = {}


def register_service(name, service_class):
    _REGISTRY[name] = service_class


def get_service(name):
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown service: {name!r}. Available: {list(_REGISTRY)}")
    return cls()


def list_services():
    return list(_REGISTRY.keys())
