"""Execution Engine - runs migration steps with rollback support."""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from ..models.migration import MigrationPlan, MigrationStep, MigrationResult, MigrationStatus, StepType
from ..utils.ssh import SSHClient

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Executes a migration plan step by step with rollback on failure."""

    def __init__(
        self,
        source_ssh: Optional[SSHClient] = None,
        target_ssh: Optional[SSHClient] = None,
        confirm_fn: Optional[Callable[[MigrationStep], bool]] = None,
        progress_fn: Optional[Callable[[MigrationStep, MigrationResult], None]] = None,
    ) -> None:
        self.source_ssh = source_ssh
        self.target_ssh = target_ssh
        self.confirm_fn = confirm_fn  # Called before each step if set
        self.progress_fn = progress_fn  # Called after each step

    def execute(self, plan: MigrationPlan, dry_run: bool = False) -> MigrationPlan:
        """Execute all steps in the migration plan.

        Args:
            plan: The migration plan to execute.
            dry_run: If True, log commands without executing.

        Returns:
            Updated plan with results.
        """
        plan.status = MigrationStatus.IN_PROGRESS
        logger.info(f"Starting migration {plan.id}: {plan.total_steps} steps")

        try:
            skipped_ids: set[int] = set()
            while True:
                step = plan.next_step(skipped=skipped_ids)
                if step is None:
                    break

                if dry_run:
                    logger.info(f"[DRY RUN] Step {step.id}: {step.description}")
                    logger.info(f"  Command: {step.command}")
                    step.completed = True
                    result = MigrationResult(step_id=step.id, success=True)
                    plan.results.append(result)
                    if self.progress_fn:
                        self.progress_fn(step, result)
                    continue

                # Confirm if needed
                if self.confirm_fn and not self.confirm_fn(step):
                    logger.info(f"Step {step.id} skipped by user")
                    skipped_ids.add(step.id)
                    plan.results.append(MigrationResult(
                        step_id=step.id, success=False, stderr="Skipped by user"
                    ))
                    continue

                # Execute step
                result = self._execute_step(step)
                plan.results.append(result)

                if result.success:
                    step.completed = True
                    step.output = result.stdout
                    logger.info(f"Step {step.id} completed ({result.duration_seconds:.1f}s)")
                else:
                    step.error = result.stderr
                    logger.error(f"Step {step.id} FAILED: {result.stderr[:200]}")

                    if step.critical:
                        logger.warning("Critical step failed - initiating rollback")
                        self._rollback(plan, step)
                        plan.status = MigrationStatus.ROLLED_BACK
                        return plan

                # Progress callback
                if self.progress_fn:
                    self.progress_fn(step, result)

            # Check if all steps completed
            if all(s.completed for s in plan.steps):
                plan.status = MigrationStatus.COMPLETED
                logger.info(f"Migration {plan.id} completed successfully!")
            else:
                plan.status = MigrationStatus.FAILED
                logger.warning(f"Migration {plan.id} finished with failures")

        except Exception as e:
            logger.error(f"Migration failed with exception: {e}")
            plan.status = MigrationStatus.FAILED
            raise

        return plan

    def _execute_step(self, step: MigrationStep) -> MigrationResult:
        """Execute a single migration step."""
        start = time.time()

        # Select SSH client based on target
        ssh = self.target_ssh if step.target == "target" else self.source_ssh

        if not ssh:
            # Run locally
            return self._run_local(step, start)

        return self._run_remote(ssh, step, start)

    def _run_local(self, step: MigrationStep, start: float) -> MigrationResult:
        """Execute step locally."""
        import subprocess
        try:
            result = subprocess.run(
                step.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=step.timeout_seconds,
            )
            return MigrationResult(
                step_id=step.id,
                success=result.returncode == 0,
                duration_seconds=time.time() - start,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return MigrationResult(
                step_id=step.id,
                success=False,
                duration_seconds=time.time() - start,
                stderr=f"Command timed out after {step.timeout_seconds}s",
                exit_code=-1,
            )

    def _run_remote(self, ssh: SSHClient, step: MigrationStep, start: float) -> MigrationResult:
        """Execute step via SSH."""
        try:
            exit_code, stdout, stderr = ssh.exec(step.command, timeout=step.timeout_seconds)
            return MigrationResult(
                step_id=step.id,
                success=exit_code == 0,
                duration_seconds=time.time() - start,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
            )
        except Exception as e:
            return MigrationResult(
                step_id=step.id,
                success=False,
                duration_seconds=time.time() - start,
                stderr=str(e),
                exit_code=-1,
            )

    def _rollback(self, plan: MigrationPlan, failed_step: MigrationStep) -> None:
        """Execute rollback commands for completed steps in reverse order."""
        logger.info("Starting rollback sequence")

        completed = [s for s in plan.steps if s.completed and s.rollback_command]
        for step in reversed(completed):
            logger.info(f"Rolling back step {step.id}: {step.description}")
            ssh = self.target_ssh if step.target == "target" else self.source_ssh

            if ssh:
                exit_code, stdout, stderr = ssh.exec(step.rollback_command, timeout=60)
                if exit_code != 0:
                    logger.error(f"Rollback failed for step {step.id}: {stderr[:200]}")
            else:
                import subprocess
                subprocess.run(step.rollback_command, shell=True, capture_output=True, timeout=60)

        logger.info("Rollback complete")
