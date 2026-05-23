"""Telegram notification for migration status."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..models.migration import MigrationPlan, MigrationStatus

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends migration status updates via Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send message to Telegram chat."""
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(self.api_url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                })
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")
            return False

    def notify_start(self, plan: MigrationPlan) -> bool:
        msg = (
            f"<b>Migration Started</b>\n"
            f"ID: <code>{plan.id}</code>\n"
            f"Source: {plan.source_host}\n"
            f"Target: {plan.target_host}\n"
            f"Services: {', '.join(plan.services)}\n"
            f"Steps: {plan.total_steps}"
        )
        return self.send(msg)

    def notify_progress(self, plan: MigrationPlan, step_desc: str) -> bool:
        msg = (
            f"<b>Migration Progress</b> [{plan.completed_steps}/{plan.total_steps}]\n"
            f"ID: <code>{plan.id}</code>\n"
            f"Step: {step_desc}"
        )
        return self.send(msg)

    def notify_complete(self, plan: MigrationPlan) -> bool:
        icon = "COMPLETED" if plan.status == MigrationStatus.COMPLETED else "FAILED"
        msg = (
            f"<b>Migration {icon}</b>\n"
            f"ID: <code>{plan.id}</code>\n"
            f"Source: {plan.source_host} -> Target: {plan.target_host}\n"
            f"Services: {', '.join(plan.services)}\n"
            f"Duration: {plan.completed_steps}/{plan.total_steps} steps"
        )
        return self.send(msg)

    def notify_rollback(self, plan: MigrationPlan) -> bool:
        msg = (
            f"<b>Migration ROLLED BACK</b>\n"
            f"ID: <code>{plan.id}</code>\n"
            f"Reason: Critical step failed\n"
            f"Completed steps rolled back successfully"
        )
        return self.send(msg)
