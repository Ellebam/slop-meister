# Atlassian sandbox

A local Jira Software and Confluence Data Center pair for running the Atlassian [service actions](service-actions.md) against real servers without touching a field instance. Use it when an Atlassian-integration change needs proof that a real Jira or Confluence accepts its requests. Automated tests keep using their local fake servers, which prove parsing and transport. The sandbox is opt-in and never runs in `task check`, CI or a routine session.

## Commands

| Command | What it does |
|---|---|
| `task sandbox:up` | Builds the sandbox from nothing, or starts a stopped one, or restarts a running one to reset the licence clock. Ends with `sandbox ready` and both addresses. |
| `task sandbox:status` | Prints `jira ready` and `confluence ready` and exits 0 only when both are running. |
| `task sandbox:live` | Delivers this checkout's service-action consumer into a temporary workspace and runs its `jira-read --issue SBX-1`, `jira-read --backlog` and `confluence-read --page <id>` through the fixed supervisor with structured input and the sandbox user's token, then every write form of `jira-write` and `confluence-write` on one target and a batch, reading each result back. Prints `JIRA_CONTEXT_PASS`, `CONFLUENCE_FETCH_PASS` and `SANDBOX_WRITE_PASS`. Each run adds two tickets and two pages. |
| `task sandbox:stop` | Stops the containers and keeps data, tokens and profiles, so the next `up` needs no 1Password approval. |
| `task sandbox:down` | Removes the sandbox containers and their volumes by project name. The next `up` rebuilds the same known state with new tokens. |

`task sandbox:live` exercises the delivered consumer and service-account path, not the agent's native approval. That flow stays under the [service-action proof](service-actions.md#verify).

## Known state

`up` from nothing runs the setup wizards unattended and leaves the same state every time. Jira has the project `SBX` with the issue `SBX-1`. Confluence has the space `SBX` with one page, whose ID is written to `~/.local/state/slopmeister/sandbox/ids.json`. Both apps have the administrator `admin` and the test user `sandbox`, and each app issues a personal access token to `sandbox`. The administrator and test-user passwords exist only in memory during setup. If setup fails partway, run `task sandbox:down` and then `task sandbox:up`. No setup step is manual.

## What it creates on this machine

- The Compose project `slopmeister-sandbox` from `slopmeister/sandbox/compose.yml`, with Postgres 16, Jira Software 10.3, Confluence 9.2 and nginx, every image pinned by digest. Only nginx publishes ports, `127.0.0.1:18443` for Jira and `127.0.0.1:18444` for Confluence, both HTTPS.
- `~/.local/state/slopmeister/sandbox/`, owner-only, holding a per-machine `localhost` certificate and key under `tls/`, the database password in `db.env` and `ids.json`. The certificate is a leaf, never a CA, and is trusted only by the sandbox profiles through `server_ca`. Nothing here is committed.
- Two API Credential items, `slopmeister-sandbox-jira-pat` and `slopmeister-sandbox-confluence-pat`, in the vault the existing service account reads. `up` writes them through desktop `op` with the token on standard input, which costs one 1Password approval per rebuild from nothing. Follow the [direct Task route](1password-access.md) from an Orca terminal; an agent whose native sandbox cannot reach desktop `op` needs native approval and a PTY. The operator handles the 1Password popup.
- The connection profiles `jira-read.json` and `confluence-read.json` under `~/.config/slopmeister/access/sandbox/` for the plot `sandbox`, written on every `up` and reused by both reads and writes. The Jira profile also contains the sandbox open-work query with deterministic key ordering. They copy the account, vault and token file from the existing field profiles, which must all agree, and pin the sandbox certificate with `server_ca`. Delivery derives each selected action; the same `sandbox` user reads and writes.

## Cost

Jira and Confluence run together with their database and proxy. Reserve memory for the full stack before starting it. Image pulls and first setup cost more than starting retained state. Coordinate capacity with other users of the Docker daemon and run `task sandbox:stop` when finished. Stop no unrelated container.

## Licence

The sandbox uses Atlassian's public [timebomb licences](https://developer.atlassian.com/platform/marketplace/timebomb-licenses-for-testing-server-apps/) for 10 users, committed in `slopmeister/sandbox/timebomb.json`. They are public configuration, not secrets. Each licence runs for 3 hours from application start, and a start or restart resets that clock. When a session runs longer, run `task sandbox:up` again. A changed image digest needs the licences and the setup proven again with `up` and `live`.

## Pulling the images

The images are public. When Docker's credential helper hangs on a pull, pull each image named in `compose.yml` anonymously with an empty client configuration, `DOCKER_CONFIG=<directory holding a {} config.json> DOCKER_HOST=<host from docker context inspect> docker pull <image>`.

## Later actions

A new Atlassian action gets its sandbox profile and its check in `live` in the change that adds the action.

## Dispatcher acceptance

Refresh the local sandbox profiles with explicitly authorized `task sandbox:up`, including when the apps are already ready. Existing `sandbox:live` fixtures provide two linked open tickets. Reuse those tickets, or separately authorize one existing `sandbox:live` fixture run, which also writes tickets/pages. Dispatcher readers themselves remain GET-only.

Prepare disposable plot declarations naming `sandbox` with only `jira-read`, alongside the Slopmeister declaration and a synthetic Jira plot verified to have no machine-local access directory. Launch a fresh dispatcher from the changed checkout with `PLOT_DECLARATIONS=<disposable-directory> task dispatch -- <tool> <unique-name>`. In that same session ask for the sandbox backlog, one linked ticket and the missing-profile plot. Expect statuses, the blocked ticket naming its open blocker, ticket summary/status/links, and unknown for the missing profile. Every read still requires native review. Preserve sanitized caller/result references and the reader revision separately from the live consumer markers.
