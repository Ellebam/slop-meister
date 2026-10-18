"""The delivered metadata command asks HA and calls only the selected vault's list API."""

import json
from pathlib import Path

from tests.integration.session.test_secret_run import TWO, op, real_calls
from tests.support.fakes import fake_binary

pytest_plugins = ("tests.integration.session.test_secret_run",)
LISTING = """
echo "$* token=${OP_SERVICE_ACCOUNT_TOKEN:-none}" >> "$HOME/real-op.log"
[ "$OP_BIOMETRIC_UNLOCK_ENABLED" = false ] || exit 7
cat <<'JSON'
[{"id":"owner-id","title":"SERVICE_ADMIN_PASSWORD","category":"PASSWORD","vault":{"id":"idtwo","name":"Production"},"fields":[{"value":"SECRET_SENTINEL"}],"notesPlain":"PRIVATE_NOTE","urls":[{"href":"PRIVATE_URL"}]},{"id":"malformed-id","title":"","category":"PASSWORD","vault":{"id":"idtwo","name":"Production"}}]
JSON
"""


def test_delivered_metadata_requires_intent_and_ha_approval(machine):
    fake_binary(Path(machine.path.split(":")[1]), "op", LISTING)
    args = ("metadata", "--vault", "Production", "--search", "service_admin")
    refused = op(machine, *args)
    assert refused.returncode == 1 and real_calls(machine) == [] and machine.asked == []
    machine.verdict = "denied"
    denied = op(machine, "tier-two", "--", "op", *args)
    assert denied.returncode == 1 and real_calls(machine) == [] and len(machine.asked) == 1
    machine.verdict = "approved"
    allowed = op(machine, "tier-two", "--", "op", *args)
    assert allowed.returncode == 0, allowed.stderr
    assert json.loads(allowed.stdout) == [
        {
            "id": "owner-id",
            "title": "SERVICE_ADMIN_PASSWORD",
            "category": "PASSWORD",
            "vault": {"id": "idtwo", "name": "Production"},
        }
    ]
    assert real_calls(machine) == [f"item list --vault=Production --format=json token={TWO}"]
    assert len(machine.asked) == 2 and "skipped 1 item(s);" in allowed.stderr
    assert all(
        value not in allowed.stdout + allowed.stderr
        for value in (
            TWO,
            "SECRET_SENTINEL",
            "PRIVATE_NOTE",
            "PRIVATE_URL",
        )
    )
