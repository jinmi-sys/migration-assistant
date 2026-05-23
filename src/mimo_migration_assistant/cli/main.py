"""Main CLI entry point using Click."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import click

from ..scraper.environment import EnvironmentScraper
from ..blueprint.generator import BlueprintGenerator
from ..credential.carrier import CredentialCarrier
from ..executor.engine import ExecutionEngine
from ..validator.lifecycle import LifecycleValidator
from ..models.migration import MigrationPlan, MigrationStatus
from ..utils.ssh import SSHClient, SSHConfig
from ..notifier.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """MiMo Migration Assistant - AI-powered environment migration."""
    setup_logging(verbose)
    ctx.ensure_object(dict)


@cli.command()
@click.argument("source")
@click.argument("target")
@click.option("--services", "-s", multiple=True, help="Specific services to migrate")
@click.option("--dry-run", is_flag=True, help="Generate plan without executing")
@click.option("--offline", is_flag=True, help="Use template-based plan (no LLM)")
@click.option("--mimo-url", default="http://localhost:11434/v1/chat/completions", help="MiMo API URL")
@click.option("--mimo-model", default="mimo-v2.5-pro", help="MiMo model name")
@click.option("--key-file", type=click.Path(exists=True), help="SSH private key file")
@click.option("--plan-out", type=click.Path(), help="Save plan to JSON file")
@click.option("--notify-telegram", is_flag=True, help="Send status to Telegram")
def migrate(
    source: str,
    target: str,
    services: tuple[str, ...],
    dry_run: bool,
    offline: bool,
    mimo_url: str,
    mimo_model: str,
    key_file: Optional[str],
    plan_out: Optional[str],
    notify_telegram: bool,
) -> None:
    """Migrate services from SOURCE to TARGET machine.

    SOURCE and TARGET can be:
    - "local" for the current machine
    - "ssh://user@host:port" for remote machines
    """
    click.echo(f"MiMo Migration Assistant")
    click.echo(f"  Source: {source}")
    click.echo(f"  Target: {target}")
    if services:
        click.echo(f"  Services: {', '.join(services)}")

    service_list = list(services) if services else None

    # Connect to machines
    source_ssh = _connect(source, key_file) if source != "local" else None
    target_ssh = _connect(target, key_file) if target != "local" else None

    try:
        # Phase 1: Scrape environments
        click.echo("\n[1/5] Scraping source environment...")
        source_scraper = EnvironmentScraper(source_ssh)
        source_env = source_scraper.scrape(service_list)
        click.echo(f"  Found {len(source_env.services)} services, {len(source_env.env_files)} env files")

        click.echo("[1/5] Scraping target environment...")
        target_scraper = EnvironmentScraper(target_ssh)
        target_env = target_scraper.scrape()
        click.echo(f"  Target: {target_env.machine.hostname} ({target_env.machine.os_type.value})")

        # Phase 2: Generate blueprint
        click.echo("\n[2/5] Generating migration blueprint...")
        generator = BlueprintGenerator(mimo_url, mimo_model)
        if offline:
            plan = generator.generate_offline(source_env, target_env, service_list)
            click.echo(f"  Offline mode: {plan.total_steps} steps generated")
        else:
            try:
                plan = generator.generate(source_env, target_env, service_list)
                click.echo(f"  MiMo generated: {plan.total_steps} steps")
            except Exception as e:
                click.echo(f"  MiMo failed ({e}), falling back to offline mode")
                plan = generator.generate_offline(source_env, target_env, service_list)

        # Show plan summary
        click.echo(f"\n  Plan: {plan.total_steps} steps, {len(plan.services)} services")
        if plan.port_mappings:
            click.echo(f"  Port remappings: {plan.port_mappings}")

        # Save plan if requested
        if plan_out:
            Path(plan_out).write_text(plan.model_dump_json(indent=2))
            click.echo(f"  Plan saved: {plan_out}")

        # Phase 3: Transfer credentials
        click.echo("\n[3/5] Transferring credentials (encrypted)...")
        if source_env.env_files and target_ssh:
            with CredentialCarrier(target_ssh) as carrier:
                encrypted = carrier.prepare_secrets(source_env.env_files)
                restored = carrier.transfer_to_target(encrypted, list(source_env.env_files.keys()))
                click.echo(f"  Transferred {len(restored)} credential files")
        else:
            click.echo("  Skipped (no env files or local target)")

        # Phase 4: Execute plan
        click.echo("\n[4/5] Executing migration plan...")
        if dry_run:
            click.echo("  DRY RUN - commands will be logged but not executed")

        # Telegram notifier
        notifier = None
        if notify_telegram:
            import os
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
            if token and chat_id:
                notifier = TelegramNotifier(token, chat_id)
                notifier.notify_start(plan)

        engine = ExecutionEngine(
            source_ssh=source_ssh,
            target_ssh=target_ssh,
            progress_fn=lambda step, result: _on_progress(step, result, notifier, plan),
        )
        plan = engine.execute(plan, dry_run=dry_run)

        if notifier:
            notifier.notify_complete(plan)

        # Phase 5: Validate
        if not dry_run and plan.status == MigrationStatus.COMPLETED:
            click.echo("\n[5/5] Validating migrated services...")
            if target_ssh:
                validator = LifecycleValidator(target_ssh)
                health = validator.validate(plan, source_env.services)
                click.echo(health.summary())
            else:
                click.echo("  Skipped (local target - run manually)")
        else:
            click.echo("\n[5/5] Skipped (dry run or migration failed)")

        # Final status
        click.echo(f"\n{'='*50}")
        click.echo(f"Migration {plan.id}: {plan.status.value.upper()}")
        click.echo(f"Steps: {plan.completed_steps}/{plan.total_steps} completed")

        if plan.status == MigrationStatus.ROLLED_BACK:
            click.echo("WARNING: Migration was rolled back due to critical failure")
            sys.exit(1)
        elif plan.status == MigrationStatus.FAILED:
            sys.exit(1)

    finally:
        if source_ssh:
            source_ssh.close()
        if target_ssh:
            target_ssh.close()


@cli.command()
@click.argument("source")
@click.option("--key-file", type=click.Path(exists=True), help="SSH private key file")
@click.option("--json-out", is_flag=True, help="Output as JSON")
def scan(source: str, key_file: Optional[str], json_out: bool) -> None:
    """Scan a machine and show discovered services."""
    ssh = _connect(source, key_file) if source != "local" else None

    try:
        scraper = EnvironmentScraper(ssh)
        env = scraper.scrape()

        if json_out:
            click.echo(json.dumps(env.to_dict(), indent=2))
        else:
            click.echo(f"Machine: {env.machine.hostname}")
            click.echo(f"  OS: {env.machine.os_type.value} {env.machine.os_version}")
            click.echo(f"  Arch: {env.machine.arch}, Cores: {env.machine.cpu_cores}, RAM: {env.machine.total_memory_mb}MB")
            click.echo(f"  Docker: {'Yes' if env.machine.docker_installed else 'No'} ({env.machine.docker_version})")
            click.echo(f"\nServices ({len(env.services)}):")
            for svc in env.services:
                ports = ", ".join(str(p.port) for p in svc.ports) or "none"
                click.echo(f"  [{svc.status.value}] {svc.name} (ports: {ports})")
            click.echo(f"\nEnv files ({len(env.env_files)}):")
            for path in env.env_files:
                click.echo(f"  {path}")
            click.echo(f"\nDocker containers ({len(env.docker_containers)}):")
            for c in env.docker_containers:
                click.echo(f"  {c.get('name', '?')} ({c.get('image', '?')})")
            click.echo(f"\nCron jobs ({len(env.cron_jobs)}):")
            for job in env.cron_jobs:
                click.echo(f"  {job[:80]}")
    finally:
        if ssh:
            ssh.close()


@cli.command()
@click.argument("plan_file", type=click.Path(exists=True))
def show_plan(plan_file: str) -> None:
    """Show a saved migration plan."""
    content = Path(plan_file).read_text()
    plan = MigrationPlan.model_validate_json(content)

    click.echo(f"Plan: {plan.id}")
    click.echo(f"Status: {plan.status.value}")
    click.echo(f"Source: {plan.source_host} -> Target: {plan.target_host}")
    click.echo(f"Services: {', '.join(plan.services)}")
    click.echo(f"\nSteps ({plan.total_steps}):")
    for step in plan.steps:
        deps = f" (after: {step.depends_on})" if step.depends_on else ""
        crit = " [CRITICAL]" if step.critical else ""
        click.echo(f"  {step.id}. [{step.step_type.value}] {step.description}{crit}{deps}")
        if step.command:
            click.echo(f"     cmd: {step.command[:80]}")


@cli.command("version")
def version_cmd() -> None:
    """Show version."""
    from .. import __version__
    click.echo(f"mimo-migration-assistant v{__version__}")


def _connect(uri: str, key_file: Optional[str] = None) -> SSHClient:
    """Create SSH client from URI."""
    config = SSHConfig.from_uri(uri)
    if key_file:
        config.key_file = key_file
    client = SSHClient(config)
    client.connect()
    return client


def _on_progress(step, result, notifier, plan) -> None:
    """Progress callback for execution engine."""
    icon = "OK" if result.success else "FAIL"
    click.echo(f"  [{icon}] Step {step.id}: {step.description} ({result.duration_seconds:.1f}s)")
    if notifier and step.id % 3 == 0:
        notifier.notify_progress(plan, step.description)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
