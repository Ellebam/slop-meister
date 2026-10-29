# Linux approval and page services

This directory owns Home Assistant approvals and Grove hosting. These services need Linux. Grove's pinned Caddy artifact supports x86-64. Slopmeister's two-tier `op` runs on macOS and Linux. It reaches the approval route over private HTTPS. Grove uses the [dedicated SSH route](../docs/remote-dispatch.md). No secret broker is installed.

## Check without deployment

From the repository root, install the optional host tools and the pinned browser dependency. Use the Node version in [.node-version](.node-version). The pinned Ansible tools require Python 3.14; select it explicitly when newer interpreters are installed.

```bash
uv sync --locked --group host --python 3.14
npm --prefix host ci --ignore-scripts
(cd host && npx playwright install chromium)
task host:lint
task host:syntax
task host:test
task host:ha:check
```

On a disposable Linux test machine or image, `cd host && npx playwright install-deps chromium` installs Chromium's system libraries. It needs administrator authority. Keep executable fixture tests in an isolated container when the host runs other workers or services. Give that container CPU and memory limits, no published ports, no host networking, no Docker socket and no account mounts.

`host:lint` uses the production Ansible profile. `host:syntax` checks every playbook against the [synthetic inventory](ansible/inventory/synthetic.yml), without executing tasks. `host:test` evaluates role and route configuration with synthetic state, drives the actual approval handlers with synthetic requests and events, exercises the Docker-control task with a stand-in, and drives the actual approval panel in Chromium. The panel's temporary loopback server stays inside the test container. No test creates or imitates a login or needs a real account or token. Handler tests use stand-ins for Home Assistant's interfaces. They do not establish its live HTTP authentication boundary.

`host:ha:check` is the separate Docker-control command. Run it from the machine that owns Docker. It streams authored configuration and synthetic route settings into the [pinned Home Assistant image](home-assistant/compose.yaml), with no mounts, no published ports and networking disabled. It bounds CPU, memory, process count and runtime, prints the created container ID, and removes only that container. It rejects a nonzero checker result, `Incorrect config` output or `ERROR:` logs even when HA returns zero. The checker also refuses warnings, including ignored packages, through `--fail-on-warnings`. Bash, GNU `timeout`, Docker and tar are required. An unavailable image must be pulled before an offline run.

These checks establish static configuration and synthetic behavior. They do not prove deployment, service restarts, notifications, real approvals or phone connectivity. Never substitute an Ansible check-mode deployment for syntax-only validation on a live host.

## Prepare the host

The operator supplies Ubuntu, an existing agent login, Python 3.14, Docker with Compose and an enrolled Tailscale daemon. The controller needs the optional host tools above. The deployment roles use privilege escalation. Set up and verify SSH host-key trust before running them.

Copy [the example inventory](ansible/inventory/example.yml) and [non-secret settings](ansible/vars.example.yml) to private files outside the checkout. Replace the host, login and time zone. `grove_python` defaults to `/usr/bin/python3.14`. Provision a supported interpreter at that path before deploying Grove.

Keep credentials out of these files. Each deployment requires `HOST_INVENTORY` and `HOST_SETTINGS`. Both deployments take `HOST_REVISION`, defaulting to `HEAD`. Select a reviewed committed revision. Before invoking a runner, each target requires its host files, included taskfiles, root Taskfile, Python project metadata, lock and local uv/Python selectors to match that revision in both the working tree and index. Nonignored untracked inputs in those paths also refuse deployment. Ignored `host/.scratch/` remains available. Use a checkout with matching reviewed inputs for rollback. Both deployments archive the resolved revision and remove their private temporary payload afterward. Home Assistant excludes ignored files and bytecode. Grove verifies its archive digest and the pinned official Caddy checksum.

```bash
task host:ha:deploy HOST_INVENTORY=/absolute/inventory.yml HOST_SETTINGS=/absolute/settings.yml HOST_REVISION=<reviewed-commit>
task host:grove:deploy HOST_INVENTORY=/absolute/inventory.yml HOST_SETTINGS=/absolute/settings.yml HOST_REVISION=<reviewed-commit>
```

Home Assistant validates the complete host configuration before startup and again before a restart handler runs. The check uses a bounded container with a read-only configuration mount and suppresses private diagnostics. Invalid retained packages or UI configuration prevent the restart. Configuration files can already have been copied when validation fails, so correct them before retrying. Expected storage-write errors from the read-only check are ignored.

Run these only for an intended deployment. They install files and start or restart the named services. They do not provision an entire workstation or change the tailnet policy. The ordinary agent account cannot replace the installed HA integration or configuration. Root and Docker administrators remain trusted.

## Home Assistant and private HTTPS

Home Assistant uses bridge networking and publishes only `127.0.0.1:8123:8123`. Bridge networking does not provide the host's LAN discovery. The configuration has no device mounts or household integrations. The first deployment starts plain Home Assistant and seeds empty UI files. It enables the approval package only after the operator supplies the protected settings below. Deployment preserves later UI edits. Root owns the deployment parents and authored files, and `.storage` is root-only.

Open `http://127.0.0.1:8123` in the host's desktop browser for first setup. The operator creates the Home Assistant account and registers the intended companion devices. Enable MagicDNS and HTTPS certificates for the tailnet. Use the host's full certificate name for remote access.

The HA role adds only `tailscale serve --bg --https=443 http://127.0.0.1:8123`. It refuses a conflicting listener, another root handler or any public Funnel. Grove uses HTTPS 8443 and a loopback backend on 8769. Both roles preserve unrelated ports and handlers. Never use a global Serve reset to resolve a conflict.

HA manages HTTP proxy trust in its UI. In Settings, System, Network, HTTP server, enable forwarded-header trust for the exact proxy peer. With Docker bridge networking this can be the bridge gateway rather than loopback. Read the gateway with `docker inspect homeassistant` and compare it with the proxy address HA reports. Trust only the verified gateway address as a `/32`, never the entire bridge subnet. Save, wait for restart, test the HTTPS login and confirm the change within HA's confirmation window. An unconfirmed change reverts. If the observed peer differs, diagnose it before granting trust.

[The example tailnet policy](tailnet-policy.example.json) admits only the selected operator and workstation tag to HTTPS 443 and 8443. It denies other users and the raw backends. Replace the example logins and merge these narrow grants and tests into the existing policy through Tailscale's editor. Preserve unrelated rules and run the provider's policy validation. This example is not a replacement for an existing full policy and adds no SSH or desktop access.

## Home Assistant approval route

Follow the [approval setup and recovery guide](approval.md) for protected settings, operator enrollment, protocol checks, rotation and migration. The route never receives a 1Password token or resolves a secret.

## Grove operation and recovery

[The Grove contract](../docs/agent-hosts.md#grove) owns publication settings, retention and the agent client. Deployment installs the reviewed intake and cleanup code under root ownership. The publisher owns the page directory. The separate reader has a read-only page mount in a jail, an execute-only Caddy binary and no access to host homes or secrets. The hourly cleanup timer runs as the publisher.

On the Grove Linux host, run `task host:grove:doctor HOST_REVISION=<reviewed-commit>`. It compares the seven-member Git archive with installed snapshot bytes and checks units and bounded loopback rejection headers. It never executes installed code. `GROVE_ENTRY` and `GROVE_BACKEND_PORT` support custom paths and ports. Missing prerequisites fail. Default HEAD checks HEAD, not a discovered deployed version. This is not a controller-side probe.

After an intended deployment, inspect `systemctl status grove.service grove-cleanup.timer`. A published page must return 200 through its verified HTTPS URL, its parent path 404, and writes must leave page bytes unchanged. Check the reader identity, jail, read-only mount and actual response CSP. Test the phone off Wi-Fi with Tailscale on. Static tests cannot establish these live observations.

A checksum mismatch or conflicting Serve route stops deployment. Resolve its cause before retrying. To roll back Grove code, deploy the preceding reviewed revision with the same protected settings. Keep credentials, registrations and pages. Restore an earlier reviewed HA configuration through its deployment target. Withdraw or replace only the exact service route on operator instruction, preserving every unrelated route.

## Public host boundaries

The host layer provides the approval and page services only. Keep these deployment boundaries when maintaining it:

| Files | Public behavior |
|---|---|
| Approval `__init__.py`, `config.py`, `question.py` and `manifest.json` | Schemas and log filtering live in `config.py`. Bounded question parsing lives in `question.py`. The component manifest links to public setup. The split preserves the approval protocol. |
| Grove defaults and entry template | Require an explicit publisher and reviewed archive. Use the declared Python 3.14 interpreter. |
| Grove tasks and service units | Refuse `root` and the reader account `grove` as publisher. Verify the archive on the controller without privilege escalation. Keep the reader separate from the page owner. |
| Both roles' `https.yml` | Own their narrow HTTPS handlers directly. Refuse Funnel and conflicting listeners while preserving unrelated routes. |
| Home Assistant role, Compose and configuration | Deploy approvals without household integrations, device mounts or automatic credential provisioning. Preserve operator-supplied settings and bounded validation. |
| Deployment entry points | Select a reviewed `HOST_REVISION`, including rollback. No deployment ancestry record or environment-specific bootstrap is required. |

The panel, UI seed files, Caddy policy and service confinement retain their existing behavior. Compare source behavior before replacing a file. A formatting or deployment-path difference alone does not justify removing these boundaries.
