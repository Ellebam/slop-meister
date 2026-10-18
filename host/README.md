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

Keep credentials out of these files. Each deployment requires `HOST_INVENTORY` and `HOST_SETTINGS`. Both deployments take `HOST_REVISION`, defaulting to `HEAD`. Select a reviewed committed revision. Before invoking a runner, each target requires its host files, included taskfiles, root Taskfile, Python project metadata, lock and local uv/Python selectors to match that revision in both the working tree and index. Nonignored untracked inputs in those paths also refuse deployment. Ignored `host/.scratch/` remains available. Use a checkout with matching reviewed inputs for rollback. Grove archives the same resolved revision, removes its temporary archive afterward and verifies its archive digest and the pinned official Caddy checksum.

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

The route receives a question and returns its decision. It never receives a 1Password token or resolves a secret. The requester gets two narrow webhook URLs and an answer credential, not a Home Assistant login token. The question webhook uses its unpredictable URL as its credential. The answer webhook also requires the bearer credential. Both URLs and the credential must stay private. Each webhook ID and the credential must contain at least 32 characters. Generate independent unpredictable values outside an agent session.

After the first plain-HA deployment, the operator creates their Home Assistant account and registers the intended companion devices through the desktop and phone apps. Open Settings > People > Users and select that operator's account. Copy its user ID, shown as `ID`, as [Home Assistant documents](https://www.home-assistant.io/integrations/person/#configuration-variables). Use the user ID, not a person or entity ID. Enable Advanced mode in the profile if the Users tab is hidden. Use only the intended operator's notification services.

At the host desk, the operator creates `/srv/homeassistant/config/secrets.yaml` under root ownership with mode `0600`. Use the configured deployment directory if it differs. Enter these settings locally, outside agent tools. These placeholders are not credentials:

```yaml
secret_approval_route_ask_url: https://YOUR_CERTIFICATE_NAME/api/webhook/YOUR_RANDOM_ASK_ID
secret_approval_route_answer_url: https://YOUR_CERTIFICATE_NAME/api/webhook/YOUR_RANDOM_ANSWER_ID
secret_approval_route_credential: YOUR_RANDOM_ANSWER_CREDENTIAL
secret_approval_route_operator: YOUR_HOME_ASSISTANT_USER_ID
secret_approval_route_devices:
  - mobile_app_YOUR_PHONE
```

Rerun `host:ha:deploy` with the same reviewed revision and private settings paths. The role inspects only file metadata, with checksum, MIME and attribute reads disabled. It refuses a nonregular, empty, non-root-owned or non-`0600` file before changing ownership. No playbook generates, reads, copies or transports credentials. If a previously installed approval package loses its settings, deployment refuses before a restart. Metadata checks cannot validate the contents. Check the HA startup log at the desk for configuration errors without sharing private settings.

Configure the requester through the [two-tier setup guide](../docs/1password-access.md). Its `home-assistant.json` uses `ask_url`, `answer_url` and `token`. The `token` is the same answer credential stored above. That credential belongs to this route only. Never substitute a Home Assistant long-lived access token. Outside agent tools, the operator first stores the two route URLs and the answer credential in their own 1Password route item. Then they put references to those three fields in their private copy of `examples/op-approval.env.example` and run the documented setup command. The env file contains references only.

A notification body tap opens the request on the approval page. Only the configured operator's authenticated Home Assistant user can read waiting questions or decide them. The notification and page bind each decision to one question ID and one sending token. The first valid decision wins. Ten minutes without a valid decision expires the question. Decisions remain readable for fifteen minutes from the question's creation. Restarting Home Assistant loses pending requests, so requesters must ask again. The panel writes question text as text. No sensor or recorder history stores waiting question details. Route logs omit webhook IDs, action tokens and companion registration error details.

With a throwaway secret, perform the [operator route checks](../docs/1password-access.md#prove-the-route) for Approve, Deny, expiry, body taps, duplicate decisions, wrong-user refusal and restart. Confirm that the answer credential is refused by unrelated HA APIs. Static handler tests and `check_config` do not prove those live authentication or notification boundaries. Confirm the ordinary agent account cannot read `secrets.yaml` or HA registration storage. Root and Docker administrators remain trusted.

For rotation, the operator replaces the route values at the desk and reruns the intended HA deployment, then updates each requester's route through the setup guide. Verify a throwaway approval. A route failure runs no waiting command. Only an explicit operator instruction selects the desktop fallback described in the secret guide.

When upgrading a previous broker installation, the operator stops and disables that retired service and removes its old bootstrap credentials through their normal credential-revocation process. This deployment removes only the retired managed panel files. It does not stop or delete an existing broker, migrate credentials or revoke them. Complete that operator migration before relying on the new route.

## Grove operation and recovery

[The Grove contract](../docs/agent-hosts.md#grove) owns publication settings, retention and the agent client. Deployment installs the reviewed intake and cleanup code under root ownership. The publisher owns the page directory. The separate reader has a read-only page mount in a jail, an execute-only Caddy binary and no access to host homes or secrets. The hourly cleanup timer runs as the publisher.

After an intended deployment, inspect `systemctl status grove.service grove-cleanup.timer`. A published page must return 200 through its verified HTTPS URL, its parent path 404, and writes must leave page bytes unchanged. Check the reader identity, jail, read-only mount and actual response CSP. Test the phone off Wi-Fi with Tailscale on. Static tests cannot establish these live observations.

A checksum mismatch or conflicting Serve route stops deployment. Resolve its cause before retrying. To roll back Grove code, deploy the preceding reviewed revision with the same protected settings. Keep credentials, registrations and pages. Restore an earlier reviewed HA configuration through its deployment target. Withdraw or replace only the exact service route on operator instruction, preserving every unrelated route.
