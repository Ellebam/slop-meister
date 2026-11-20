# GitLab through glab

Agents use `glab` for GitLab as they use `gh` for GitHub, including self-managed hosts. Hosts, group paths and project names stay in the owning vault note, 1Password item and `glab` configuration, never this repository.

## Set up the login

1. Install the CLI with `brew install glab`. `brew upgrade glab` keeps it current, and the [workstation skill](../src/skills/workstation/SKILL.md) reports it when it is behind.
2. Create a personal access token in the host's user settings, under Access, Personal access tokens. A single sign-on account can create one, because GitLab keeps its own user behind the sign-on. Choose scope `api` for read and write, or `read_api` when the host must refuse every write. Set an expiry.
3. Store the token and bare host name, without `https://`, in your own 1Password item. Copy [the neutral reference example](../examples/glab.env.example) to `~/.config/slopmeister/glab.env`, outside the checkout, and set mode `0600`. Set `SLOPMEISTER_GLAB_TOKEN` and `SLOPMEISTER_GLAB_HOST` to your `op://` references. Keep actual values and account-specific references out of this repository.
4. Run `task glab:login`. The target reads that private file through `op run --env-file` and uses the [secret request route](1password-access.md). The expected output is `GLAB_LOGIN_PASS`. A failure prints `GLAB_LOGIN_FAIL` with the reason and never the token or the host.

The target sends the token through masked `op run` to `glab auth login --stdin`. `glab` stores it in the macOS keychain so Orca can call it outside Task. Its configuration holds no token. Renew an expired token with steps 2 to 4.

`bin/slopmeister workstation doctor` reports `tool:glab` and `login:glab`. `glab auth status` exits 1 while the unused `gitlab.com` entry has no token, so the doctor accepts one logged-in host and reports `glab auth status exited 1, one host is logged in`.

## Read

Name projects with `-R <host>/<group>/<project>`. Group reads use `GITLAB_HOST=<host>` and `--group <group>`. Add `-F json` to `issue` and `mr` for JSON. Use these named reads when they provide the requested result. Write an API-only repository or tracker read inside the project's checkout as `glab api -X GET <endpoint>` with the query in the URL. Claude runs that form by [rule](permissions.md). Place the host before the method for a read from another host. The reviewer checks the destination. A host after the method, a field option or a credential endpoint asks the operator. The read request supplies task authority without a separate write order. GET alone does not make an endpoint safe. [`glab api`](https://docs.gitlab.com/cli/api/) has no `--jq`, so pipe its JSON to `jq`.

| Command | Expected output, exit 0 |
|---|---|
| `glab issue view <n> --comments -R <host>/<group>/<project>` | `title:`, `state:`, `author:`, `labels:`, `comments:` and `assignees:` lines, then the description and every comment |
| `glab issue list -R <host>/<group>/<project>` | `Showing <n> open issues in <group>/<project>`, then one line per issue with ID, title, labels and age |
| `GITLAB_HOST=<host> glab issue list --group <group>` | The same list across every project of the group |
| `GITLAB_HOST=<host> glab mr list --group <group>` | One line per open merge request, or `No open merge requests available on <group>.` |
| `glab mr view <n> --comments -R <host>/<group>/<project>` | The merge request with its description and comments |
| `GITLAB_HOST=<host> glab work-items list --group <group> --type epic` | One line per epic with type, IID, title, state and author |
| `GITLAB_HOST=<host> glab iteration list --group <group>` | One line per iteration with its title and link |

`glab issue board view -R <host>/<group>/<project>` shows a project's issue board. Read group epic boards in the browser. [Legacy epic notes](https://docs.gitlab.com/api/notes/#epics) need the numeric epic ID, not its IID. That API is deprecated. Use Work Items for newer epics.

For an existing GitLab task branch with a different name, add `--push-branch /path/to/shop feature/shop-search` when launching the worker. The [launcher guide](launcher.md#declared-shipping) explains how to push the saved branch, optionally include a pre-release tag and open a merge request.

For a self-managed host, use `glab api --hostname <host> --method GET <endpoint>`. The explicit host and read method keep the destination and operation visible.

## Ship a branch

Launch the worker with a branch belonging to the selected repository. With the plot’s commit and shipping grants, its fixed ship helper can push the saved non-default branch. Use the forge’s normal merge-request route for review. The [shipping procedure](../src/skills/ship/SKILL.md) lists the allowed targets and required checks.

## Write

Each write needs the operator's request for that exact command and target in the conversation. This covers issue, merge request, work item, pipeline, release and project writes, `glab api`, and every other `glab` subcommand that creates, edits, deletes or publishes. `glab auth` and `glab config` are refused, because they change the stored login or can print the token. [src/permissions.toml](../src/permissions.toml) lists every entry. A refusal matches the direct command only. A flag before the subcommand, as in `glab --repo <project> config`, evades it.

Run [Rinse](../src/skills/rinse/SKILL.md) on every outward draft before showing or sending it, including text for projects we own.

## In Orca

Orca's Tasks view runs on `glab` and uses the same login. No second credential and no Orca setting is needed, because Orca lists GitLab among its task sources by default.

Orca finds GitLab work through a registered repository whose Git remote points at the host. No settings file can hold these steps.

1. Clone the project that holds the issues, over SSH, outside every Slopmeister worktree.
2. Register it with `orca repo add --path <clone>`.
3. Open Tasks, choose GitLab, and select only GitLab repositories in the repository selector. One selected GitHub repository fails the whole list with `None of the git remotes configured for this repository point to a known GitLab host`.

| Item | In Orca's GitLab view |
|---|---|
| Issues | Shown, with the filters Open and Assigned to me. Each row opens in Orca or in the browser |
| Merge requests | Shown, with the filters Open, Merged, Closed and All |
| To-do items | Shown under My Todos |
| Work items | Shown as issues only |
| Epics, boards, iterations | Not shown. Read epics and iterations with `glab`, and boards in the browser |

Leave Orca's start-a-workspace action on a GitLab item unused, as [Orca onboarding](orca.md#working-in-orca) says for every Orca launch. A worker starts through the launcher. Orca does not link a GitLab item to a launcher workspace, because that workspace belongs to the plot's repository and `orca worktree set` links GitHub and Linear items only. Name the item in the kickoff instead.

## Tasks from GitLab

No plot declares GitLab as its task source. A plot whose work is tracked there keeps `tasks = "manual"`, and its vault context note names the project. Start a worker from a work item with a kickoff file that opens with the mode line and carries the item's text. [Task briefs](contracts.md) owns what a kickoff needs.

```bash
{ printf 'Mode: spine\n\n'; glab issue view <n> -R <host>/<group>/<project>; } > <kickoff file>
task kickoff:check -- <kickoff file>
task plot-session -- <plot> <name> < <kickoff file>
```

The launcher claims nothing on GitLab.
