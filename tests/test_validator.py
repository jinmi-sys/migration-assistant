"""Tests for lifecycle validator."""

from mimo_migration_assistant.validator.lifecycle import LifecycleValidator, HealthReport, MigrationHealthReport


class TestHealthReport:
    def test_healthy_report(self):
        report = HealthReport(service_name="nginx", healthy=True)
        assert report.status_icon == "OK"

    def test_failed_report(self):
        report = HealthReport(service_name="nginx", healthy=False)
        assert report.status_icon == "FAIL"


class TestMigrationHealthReport:
    def test_summary(self):
        report = MigrationHealthReport(
            plan_id="test",
            reports=[
                HealthReport(service_name="nginx", healthy=True, checks_passed=["port_80"]),
                HealthReport(service_name="redis", healthy=False, checks_failed=["port_6379_not_listening"]),
            ],
            overall_healthy=False,
            duration_seconds=5.0,
        )
        assert report.total_services == 2
        assert report.healthy_count == 1
        assert report.failed_count == 1
        summary = report.summary()
        assert "nginx" in summary
        assert "redis" in summary
        assert "1/2" in summary


class TestLifecycleValidator:
    def test_validate_calls_checks(self, sample_plan, mock_ssh, sample_services):
        validator = LifecycleValidator(mock_ssh)
        report = validator.validate(sample_plan, sample_services[:1])
        assert report.total_services == 1
