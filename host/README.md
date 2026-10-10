# Linux approval and page services

This directory owns Home Assistant approvals, the secret broker and Grove hosting. The services need Linux. Grove's pinned Caddy artifact supports x86-64. Slopmeister's agent clients also run on macOS, where they reach the broker and Grove through the [dedicated SSH route](../docs/remote-dispatch.md).

## Check without deployment

From the repository root, install the optional host tools and the pinned browser dependency. Use the Node version in [.node-version](.node-version).

```bash
uv sync --locked --group host
npm --prefix host ci --ignore-scripts
(cd host && npx playwright install chromium)
task host:lint
task host:syntax
task host:test
task host:ha:check
```

On a disposable Linux test machine or image, `cd host && npx playwright install-deps chromium` installs Chromium's system libraries. It needs administrator authority. Keep executable fixture tests in an isolated container when the host runs other workers or services. Give that container CPU and memory limits, no published ports, no host networking, no Docker socket and no account mounts.

`host:lint` uses the production Ansible profile. `host:syntax` checks every playbook against the [synthetic inventory](ansible/inventory/synthetic.yml), without executing tasks. `host:test` evaluates role and route configuration with synthetic state, exercises the Docker-control task with a stand-in, and drives the actual approval panel in Chromium. The panel's temporary loopback server stays inside the test container. No test needs an account or token.

`host:ha:check` is the separate Docker-control command. Run it from the machine that owns Docker. It streams authored configuration into the [pinned Home Assistant image](home-assistant/compose.yaml), with no mounts, no published ports and networking disabled. It bounds CPU, memory, process count and runtime, prints the created container ID, and removes only that container. It rejects a nonzero checker result, `Incorrect config` output or `ERROR:` logs even when HA returns zero. Warnings alone do not fail the check. Bash, GNU `timeout`, Docker and tar are required. An unavailable image must be pulled before an offline run.

These checks establish static configuration and synthetic behavior. They do not prove deployment, service restarts, notifications, real approvals or phone connectivity. Never substitute an Ansible check-mode deployment for syntax-only validation on a live host.

## Prepare the host

The operator supplies Ubuntu, an existing agent login, Python 3.14 as the default `python3`, with its venv support, Docker with Compose, the 1Password CLI at `/usr/bin/op`, and an enrolled Tailscale daemon. The controller needs the optional host tools above. The deployment roles use privilege escalation. Set up and verify SSH host-key trust before running them.

Copy [the example inventory](ansible/inventory/example.yml) and [non-secret settings](ansible/vars.example.yml) to private files outside the checkout. Replace the host, login, time zone and requesting account. The requesting account needs a same-named group for the broker's supplementary access. `secret_ask_python` and `grove_python` default to `/usr/bin/python3.14`. `secret_ask_venv_package` names the corresponding Ubuntu venv package. Provision a supported interpreter at that path before deployment.

Keep credentials out of these files. Each deployment requires `HOST_INVENTORY` and `HOST_SETTINGS`. All three deployments take `HOST_REVISION`, defaulting to `HEAD`. Select a reviewed committed revision. Before invoking a runner, each target requires its host files, included taskfiles, root Taskfile, Python project metadata, lock and local uv/Python selectors to match that revision in both the working tree and index. Nonignored untracked inputs in those paths also refuse deployment. Ignored `host/.scratch/` remains available. Use a checkout with matching reviewed inputs for rollback. Broker and Grove archive the same resolved revision and remove their temporary archives afterward. Broker runtime dependencies are exported from its lock and installed with hashes. Grove verifies its archive digest and the pinned official Caddy checksum.

```bash
task host:ha:deploy HOST_INVENTORY=/absolute/inventory.yml HOST_SETTINGS=/absolute/settings.yml HOST_REVISION=<reviewed-commit>
task host:broker:deploy HOST_INVENTORY=/absolute/inventory.yml HOST_SETTINGS=/absolute/settings.yml HOST_REVISION=<reviewed-commit>
task host:grove:deploy HOST_INVENTORY=/absolute/inventory.yml HOST_SETTINGS=/absolute/settings.yml HOST_REVISION=<reviewed-commit>
```

Run these only for an intended deployment. They install files and start or restart the named services. They do not provision an entire workstation or change the tailnet policy. The ordinary agent account cannot replace the installed broker code or HA configuration. Root and Docker administrators remain trusted.

## Home Assistant and private HTTPS

Home Assistant uses bridge networking and publishes only `127.0.0.1:8123:8123`. Bridge networking does not provide the host's LAN discovery. The configuration has no device mounts or household integrations. The plain configuration supplies the approval package and seeds empty UI files. Deployment preserves later UI edits. Root owns the deployment parents and authored files, and `.storage` is root-only.

Open `http://127.0.0.1:8123` in the host's desktop browser for first setup. The operator creates the Home Assistant account and registers the intended companion devices. Enable MagicDNS and HTTPS certificates for the tailnet. Use the host's full certificate name for remote access.

The HA role adds only `tailscale serve --bg --https=443 http://127.0.0.1:8123`. It refuses a conflicting listener, another root handler or any public Funnel. Grove uses HTTPS 8443 and a loopback backend on 8769. Both roles preserve unrelated ports and handlers. Never use a global Serve reset to resolve a conflict.

HA manages HTTP proxy trust in its UI. In Settings, System, Network, HTTP server, enable forwarded-header trust for the exact proxy peer. With Docker bridge networking this can be the bridge gateway rather than loopback. Read the gateway with `docker inspect homeassistant` and compare it with the proxy address HA reports. Trust only the verified gateway address as a `/32`, never the entire bridge subnet. Save, wait for restart, test the HTTPS login and confirm the change within HA's confirmation window. An unconfirmed change reverts. If the observed peer differs, diagnose it before granting trust.

[The example tailnet policy](tailnet-policy.example.json) admits only the selected operator and workstation tag to HTTPS 443 and 8443. It denies other users and the raw backends. Replace the example logins and merge these narrow grants and tests into the existing policy through Tailscale's editor. Preserve unrelated rules and run the provider's policy validation. This example is not a replacement for an existing full policy and adds no SSH or desktop access.

## Broker credentials and first approval

The first broker deployment creates the non-login service account and protected runtime, then leaves the service stopped until both bootstrap files are ready. It checks only file metadata, with checksum, MIME and attribute reads disabled. No playbook reads, copies or transports token values.

Create a 1Password service account with read access to the custom vaults that approved requests may need. Its token must remain outside agent-readable stores. Create a Home Assistant token for the intended operator. Set `secret_ask_operator` to that operator's user ID and `secret_ask_devices` to the registered notification service names. Obtain the user ID through an authenticated `auth/current_user` WebSocket call without recording its access token. Use only the intended operator's devices.

At the Linux host's desk, outside an agent tool, the operator enters each token through a hidden prompt:

```bash
systemd-ask-password 'Broker 1Password token' | sudo install -o slopmeister-secret-ask -g slopmeister-secret-ask -m 0600 /dev/stdin /etc/slopmeister-secret-ask/onepassword-token
systemd-ask-password 'Broker Home Assistant token' | sudo install -o slopmeister-secret-ask -g slopmeister-secret-ask -m 0600 /dev/stdin /etc/slopmeister-secret-ask/home-assistant-token
```

Rerun the same broker deployment. It enables the service only when both files are regular, nonempty and owned by the broker with mode `0600`. Inspect `systemctl status slopmeister-secret-ask.service`. Confirm the ordinary agent account cannot read the token files or HA registration storage. These permissions do not isolate a hostile administrator.

Set companion server URLs to the verified tailnet HTTPS origin. With a throwaway secret, perform the [operator route checks](../docs/1password-access.md#prove-the-route) for Approve, Deny, expiry, body taps, duplicate decisions and reboot. The panel renders request data as text and keeps each decision bound to its displayed request. The `sensor.secret_ask` entity and its live request attributes are excluded from recorder history. This does not claim to exclude action tokens carried by other events. The broker, not the visible button, checks the authenticated operator and action token.

For rotation, stop the broker, enter replacements through the same desk commands, start it and verify a throwaway approval before revoking the old credentials. A broker outage follows the [existing desktop fallback](../docs/1password-access.md#when-the-broker-is-unreachable). Agents cannot choose that route themselves.

## Grove operation and recovery

[The Grove contract](../docs/agent-hosts.md#grove) owns publication settings, retention and the agent client. Deployment installs the reviewed intake and cleanup code under root ownership. The publisher owns the page directory. The separate reader has a read-only page mount in a jail, an execute-only Caddy binary and no access to host homes or secrets. The hourly cleanup timer runs as the publisher.

After an intended deployment, inspect `systemctl status grove.service grove-cleanup.timer`. A published page must return 200 through its verified HTTPS URL, its parent path 404, and writes must leave page bytes unchanged. Check the reader identity, jail, read-only mount and actual response CSP. Test the phone off Wi-Fi with Tailscale on. Static tests cannot establish these live observations.

A checksum mismatch or conflicting Serve route stops deployment. Resolve its cause before retrying. To roll back broker or Grove code, deploy the preceding reviewed revision with the same protected settings. Keep credentials, registrations and pages. Restore an earlier reviewed HA configuration through its deployment target. Withdraw or replace only the exact service route on operator instruction, preserving every unrelated route.
