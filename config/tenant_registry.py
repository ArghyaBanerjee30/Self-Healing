from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class EntryPoint:
    service: str
    router: Optional[str] = None
    service_layer: Optional[str] = None
    repository_layer: Optional[str] = None
    log_pattern: Optional[str] = None


@dataclass
class TenantConfig:
    project_id: str
    production_log: str
    entry_points: List[EntryPoint] = field(default_factory=list)

    def service_for_log_pattern(self, path: str) -> Optional[str]:
        for ep in self.entry_points:
            if ep.log_pattern and ep.log_pattern in path:
                return ep.service
        return None

    @classmethod
    def from_yaml(cls, path: str) -> "TenantConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        stack = data.get("stack", {})
        entry_points = [
            EntryPoint(
                service=ep["service"],
                router=ep.get("router"),
                service_layer=ep.get("service_layer"),
                repository_layer=ep.get("repository_layer"),
                log_pattern=ep.get("log_pattern"),
            )
            for ep in stack.get("entry_points", [])
        ]
        return cls(
            project_id=data["project"]["id"],
            production_log=stack.get("production_log", ""),
            entry_points=entry_points,
        )
