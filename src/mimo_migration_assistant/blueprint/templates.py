"""Script templates for migration steps."""

from __future__ import annotations

from jinja2 import Template

STOP_SERVICE_TPL = Template("""
# Stop {{ name }}
{% if docker_container %}
docker stop {{ docker_container }}
{% elif systemd_unit %}
systemctl stop {{ name }}
{% elif pid %}
kill {{ pid }} && sleep 2
{% else %}
pkill -f {{ name }} || true
{% endif %}
""")

START_SERVICE_TPL = Template("""
# Start {{ name }}
{% if docker_container %}
docker start {{ docker_container }}
{% elif systemd_unit %}
systemctl start {{ name }}
systemctl enable {{ name }}
{% else %}
# Manual start required for {{ name }}
{% endif %}
""")

COMPRESS_TPL = Template("""
# Compress {{ name }} data
tar czf /tmp/migrate_{{ name }}.tar.gz {% for p in paths %}{{ p }} {% endfor %}
""")

HEALTH_CHECK_TPL = Template("""
# Health check {{ name }}
{% if port %}
curl -sf --max-time 5 http://localhost:{{ port }}/health || \
curl -sf --max-time 5 http://localhost:{{ port }}/ || \
{ echo "FAIL: {{ name }} not responding on port {{ port }}"; exit 1; }
{% elif systemd_unit %}
systemctl is-active {{ name }}
{% else %}
pgrep -f {{ name }}
{% endif %}
""")


class ScriptTemplate:
    """Renders migration step templates."""

    @staticmethod
    def stop_service(name: str, docker_container: str = "", systemd_unit: str = "", pid: int = 0) -> str:
        return STOP_SERVICE_TPL.render(name=name, docker_container=docker_container, systemd_unit=systemd_unit, pid=pid or "")

    @staticmethod
    def start_service(name: str, docker_container: str = "", systemd_unit: str = "") -> str:
        return START_SERVICE_TPL.render(name=name, docker_container=docker_container, systemd_unit=systemd_unit)

    @staticmethod
    def compress(name: str, paths: list[str]) -> str:
        return COMPRESS_TPL.render(name=name, paths=paths)

    @staticmethod
    def health_check(name: str, port: int = 0, systemd_unit: str = "") -> str:
        return HEALTH_CHECK_TPL.render(name=name, port=port or "", systemd_unit=systemd_unit)
