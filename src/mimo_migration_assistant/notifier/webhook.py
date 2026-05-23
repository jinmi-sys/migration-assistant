"""Generic webhook notifier."""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from ..models.migration import MigrationPlan

logger = logging.getLogger(__name__)


class WebhookNotifier:
    """Sends migration events to a generic webhook URL."""

    def __init__(self, url: str, headers: Optional[dict] = None) -> None:
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}

    def send(self, event: str, plan: MigrationPlan, extra: Optional[dict] = None) -> bool:
        payload = {
            "event": event,
            "plan_id": plan.id,
            "source": plan.source_host,
            "target": plan.target_host,
            "services": plan.services,
            "status": plan.status.value,
            "completed_steps": plan.completed_steps,
            "total_steps": plan.total_steps,
            **(extra or {}),
        }
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(self.url, json=payload, headers=self.headers)
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Webhook notification failed: {e}")
            return False
