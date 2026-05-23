"""Tests for execution engine."""

from mimo_migration_assistant.executor.engine import ExecutionEngine
from mimo_migration_assistant.models.migration import (
    MigrationPlan, MigrationStep, StepType, MigrationStatus,
)


class TestExecutionEngine:
    def test_dry_run(self, sample_plan):
        engine = ExecutionEngine()
        result = engine.execute(sample_plan, dry_run=True)

        assert result.status == MigrationStatus.COMPLETED
        assert all(s.completed for s in result.steps)
        assert len(result.results) == 5

    def test_next_step_respects_dependencies(self, sample_plan):
        step = sample_plan.next_step()
        assert step.id == 1

        sample_plan.steps[0].completed = True
        step = sample_plan.next_step()
        assert step.id in (2, 3)

    def test_confirm_fn_skip(self, sample_plan):
        def deny_all(step):
            return False

        engine = ExecutionEngine(confirm_fn=deny_all)
        result = engine.execute(sample_plan, dry_run=False)
        assert result.status == MigrationStatus.FAILED

    def test_progress_callback(self, sample_plan):
        calls = []

        def on_progress(step, result):
            calls.append((step.id, result.success))

        engine = ExecutionEngine(progress_fn=on_progress)
        engine.execute(sample_plan, dry_run=True)
        assert len(calls) == 5

    def test_empty_plan(self):
        plan = MigrationPlan()
        engine = ExecutionEngine()
        result = engine.execute(plan, dry_run=True)
        assert result.status == MigrationStatus.COMPLETED
