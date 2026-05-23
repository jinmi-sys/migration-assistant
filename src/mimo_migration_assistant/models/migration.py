"""Migration plan and result models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class MigrationStatus(str, enum.Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class StepType(str, enum.Enum):
    STOP_SERVICE = "stop_service"
    COMPRESS_DATA = "compress_data"
    TRANSFER_FILE = "transfer_file"
    INSTALL_PACKAGE = "install_package"
    CONFIGURE_SERVICE = "configure_service"
    SET_PERMISSIONS = "set_permissions"
    CONFIGURE_FIREWALL = "configure_firewall"
    START_SERVICE = "start_service"
    HEALTH_CHECK = "health_check"
    ROLLBACK = "rollback"


class MigrationStep(BaseModel):
    """Single atomic step in a migration plan."""

    id: int
    step_type: StepType
    description: str
    command: str = ""
    target: str = "source"  # "source" or "target"
    depends_on: list[int] = Field(default_factory=list)
    timeout_seconds: int = 300
    rollback_command: Optional[str] = None
    critical: bool = True  # If True, failure triggers rollback
    completed: bool = False
    output: str = ""
    error: str = ""


class MigrationResult(BaseModel):
    """Result of executing a single step."""

    step_id: int
    success: bool
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


class MigrationPlan(BaseModel):
    """Complete migration plan from source to target."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: MigrationStatus = MigrationStatus.PLANNED
    source_host: str = ""
    target_host: str = ""
    services: list[str] = Field(default_factory=list)
    steps: list[MigrationStep] = Field(default_factory=list)
    results: list[MigrationResult] = Field(default_factory=list)
    port_mappings: dict[int, int] = Field(default_factory=dict)
    notes: str = ""

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def completed_steps(self) -> int:
        return sum(1 for s in self.steps if s.completed)

    @property
    def progress_pct(self) -> float:
        if not self.steps:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100

    def next_step(self, skipped: Optional[set[int]] = None) -> Optional[MigrationStep]:
        by_id = {s.id: s for s in self.steps}
        skip = skipped or set()
        for step in self.steps:
            if not step.completed and step.id not in skip:
                deps_met = all(
                    by_id[d].completed for d in step.depends_on if d in by_id
                )
                if deps_met:
                    return step
        return None
