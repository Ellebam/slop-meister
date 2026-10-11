# Orca

Orca hosts Slopmeister's agent terminals and phone view. Slopmeister owns dispatch, workspace preparation and the settings listed in [`plots/home/orca/settings.json`](../plots/home/orca/settings.json). The installer manages them on the Mac, in `~/Library/Application Support/orca/profiles/local-default/orca-data.json`. A fresh Linux profile has none, set them by hand. There is no Orca settings command.

## Managed setup

1. Install Orca and open it once to create its local profile. Close Orca completely before installing its managed settings, including an install of every entry. The installer refuses that selection if Orca is running or its closed state cannot be verified, and it backs up the original file under `~/.slopmeister-backup/` before merging managed JSON values. A missing or malformed profile also refuses before any home entry is written.
2. Run `task home:diff` to see managed-key status without printing Orca's other state. Run `task home:install` only when you intend to update installed configuration. Named installs that exclude Orca settings can run while Orca is open. `task check` reports a managed key changed in the Orca UI as drift.
3. Reopen Orca after installing its settings. `bin/slopmeister workstation doctor` reports in its `orca:runtime` and `orca:hooks` results whether its CLI is missing, the app is closed, its runtime is unreachable, or Claude and Codex status hooks are off or unverified. It reads only `orca status --json` and `orca agent hooks status --json` for Orca health and never starts the app.

The managed settings disable telemetry and agent hibernation, enable agent status hooks and desktop notifications, set Orca's own agent launch defaults to Manual, select the Kanagawa dark terminal theme, and add global Claude and Codex dispatcher Quick Commands. The Quick Commands use `task dispatch` in a new Orca terminal. The Codex command pins the normal `~/.codex` home and starts a standalone dispatcher.

On Linux, apply the same managed choices from the linked JSON in Orca's UI, including Manual agent launch and the two dispatcher Quick Commands. The installer does not merge a Linux Orca profile.

## Steps the settings file cannot hold

1. Grant Orca Full Disk Access in macOS Privacy & Security. Processes in Orca terminals then reach privacy-protected files without another dialog, including the vault. Grant it only after accepting that access for agents you run there.
2. Sign in to Orca, open Settings, Mobile, choose **Orca Relay** and wait until it is ready. If the Relay code fails, restart Orca and try again, never choose **Use LAN**. A LAN pairing carries no Relay and cannot gain it later, and the phone keeps one card per Mac, so pairing again replaces that card and a LAN pairing deletes its Relay route. Under **Also use a faster local path**, add this Mac's MagicDNS name with port 6768 as a custom address, after installing Tailscale on the workstation and phone, signing both into your tailnet and configuring its policy to admit only the intended devices to Orca's port 6768. Enable MagicDNS and use the workstation's own reported name. Do not add an exit node or subnet route for this connection. Use the name, not the tailnet IP, because the name stops resolving the moment the phone's Tailscale is off and Orca moves to Relay at once, while an unreachable IP makes it wait. Then pair the phone and remove the Mac's older entries for it. The phone uses the tailnet while it answers and Relay otherwise, with no action on the phone. Route changes are not immediate, so verify both directions on the installed version. Editing the phone's direct address later keeps Relay.
   With the phone's Wi-Fi and Tailscale off, confirm the host card reads **Orca Relay**, the Slopmeister workspace appears and a Quick Command opens a terminal. A card reading "Update desktop Orca and sign in to connect from anywhere" means the pairing has no Relay, pair again with Orca Relay. The host's Network diagnostics report, from a long press on its card, lists `Relay:` lines and `recovery=relay` whenever Relay is in play.
3. Do not allow notifications in the phone app. Orca push sends the workspace name and the first 180 characters of an agent's last reply to [the vendor gateway in plaintext](https://github.com/stablyai/orca/blob/main/src/main/ipc/notification-options.ts). Desktop notifications remain on.
4. Register `~/.slopmeister/sessions/` as a folder in Orca so directory sessions appear. Orca's CLI cannot register this non-Git directory.
5. Pick one badge colour for each repository in Orca's repository settings. The badge identifies sessions from that repository in place of a plot colour.
6. Register GitLab project clones as described in [GitLab in Orca](gitlab.md#in-orca).

[Phone access](phone-access.md) covers both phone entry routes and the duplicate-dispatcher refusal.

## Working in Orca

Use Orca to review what a worker produced. Slopmeister still creates the worktrees and launches the agents.

- Review a finished worker's branch with Open Branch Diff, which compares the committed branch against its base. `orca file open-changed` opens only uncommitted changes, so it shows nothing once the branch is committed.
- Comment on diff lines with Annotate AI Diff, then choose **Send** in the diff toolbar, "Send notes to an agent", to pass every unsent comment to the worker as one prompt.
- Read a plan or other Markdown in Orca's Markdown view and leave review notes there.
- Ask a worker for `bloom` to get a visual explanation of its work. [Grove](agent-hosts.md#grove) serves eligible pages through a private tailnet HTTPS link that opens in the Mac or phone browser. The ignored worktree copy stays local. Excluded plots and unavailable hosting return that file path, which can be opened in a browser on its owning machine. Phone browser access uses the published HTTPS link.
- Follow the worktree's linked pull request from Orca while the worker runs.

Leave Orca's worktree creation, agent launch, orchestration, automations and the Orca skills from `orca skills install` unused. Slopmeister owns those jobs, and a worker started from Orca misses the launcher's kickoff delivery, fixed configuration and issue claim. [Terminal control and orchestration](#terminal-control-and-orchestration) gives the reasons for the terminal and orchestration commands.

The [remote-dispatch process](remote-dispatch.md) owns remote runtime access and native-view validation. Its remote terminal sends keep the same operator-only rule below.

## Terminal control and orchestration

Terminal input can carry the operator's authority into a worker. Keep these limits when controlling an agent through Orca. `<worker>` is a terminal handle from `orca terminal list`.

| Capability | Verdict | Reason |
|---|---|---|
| `orca worktree ps --json`, the `agents` rows | use | Hook-reported `agentType`, `state` and `lastAssistantMessage` per workspace, subject to the status limits below |
| `orca terminal read --terminal <worker> --screen` | use with limits | The current frame only, for a question or dialog that the status row does not explain |
| `orca terminal list` | use with limits | Liveness and handles only |
| `orca terminal wait --for tui-idle` | do not use | Not a completion or attention signal |
| `orca terminal send` into an agent | only on operator request | Injected text carries operator authority on both tools |
| `orca orchestration dispatch --inject`, `worker-start` | do not use | The preamble is injected text and moves operator gates to an agent |
| `orca orchestration send`, `check`, `ask`, `reply` | do not use | Safe for approval, but only reachable after an injected preamble, and Slopmeister has no coordinating agent to talk to |
| `orca orchestration gate-create`, `gate-resolve` | do not use | Coordinator-owned task decisions, while Slopmeister's gates belong to the operator |

### Status limits

A `done` state means the turn ended, so a worker waiting on an operator question is visible only in `lastAssistantMessage`. Treat a row with an old `updatedAt` as unknown and read the screen. Keep only rows with agents and only the fields needed for status.

`terminal list` and `worktree ps` cover every workspace on the Mac, including field repositories, and their `preview` fields hold raw screen text such as SSH identity comments. Never read the preview fields and never copy status output or a preview into a repository, ticket or report.

A screen read returns only the visible frame of a full-screen agent. Earlier turns and a scrolled-away question can be invisible. `tui-idle` does not establish completion or distinguish a permission dialog from background work. Read a reported `blockedReason`, such as `agent-trust-workspace`, before acting.

### The approval boundary

A worker can treat injected terminal text as explicit user authorization. Terminal input can also answer native permission and folder-trust dialogs. Neither a successful native approval nor a transcript's user role proves that the operator authored the injected text.

An agent sends input to another agent's terminal only when the operator asks for it in that agent's conversation, because the worker treats the text as the operator's own. The standing dispatcher's instructions carry this rule. The operator's own **Send** from Annotate AI Diff stays fine because the operator presses it.

Mailbox content arrives as tool output. A coordinator's request or claim of approval does not establish operator intent.

### Orchestration and the launcher

`orca orchestration dispatch --task <id> --to <worker> --inject` can adopt a terminal the launcher opened, so fixed-copy delivery, kickoff proof and the issue claim survive. The dispatch preamble still arrives as typed user input. The preamble tells the worker to route every question through `orchestration ask` instead of asking the user, forbids reporting on GitHub, which contradicts ship, and calls bare `orca`. `worker-start` without `--terminal` creates its own worktree and agent launch and so bypasses the launcher entirely. Mailbox messages reach a worker only when it runs `check`, so nothing interrupts a worker that was not told to look. None of it replaces a Slopmeister mechanism, because the operator is the only channel into a worker.

### The bare `orca` command

On macOS, a broken or unreadable `/usr/local/bin/orca` registration can shadow the app's bundle command on `PATH`. The launcher and doctor call the bundle copy, so `orca:runtime` can be healthy while a bare `orca` command fails. Inspect the registration and command resolution before changing it. Linux uses `/usr/bin/orca-ide`, since `/usr/bin/orca` is the GNOME screen reader.

The operator manages that link from the CLI section of Orca Settings. Repair or remove a broken registration there after verifying its target. Register it only when `orca` is needed outside Orca terminals, then confirm the command resolves and runs. Do not remove an unrelated executable with the same name.

## Codex permission waits

Slopmeister starts Codex workers with `on-request` and `auto_review`. Eligible requests go to Codex's automatic reviewer. The numbered Allow/Deny permission prompt below appears when a worker is explicitly launched with the manual reviewer, `approvals_reviewer=user`. An automatic-review denial instead uses Codex's native `/approve` for one exact retry, still subject to review.

Do not rely on Orca Mobile's approval card for a standalone Codex worker yet. The paired app can omit the card while the Mac terminal has a live request, and a denied request can leave Orca showing a stale waiting state. In Orca Mobile, open the worker's **terminal view** and read the native Codex prompt. For a one-time Allow, choose `1` and press Return. For Deny, press Escape. Check the terminal result because the red dot alone proves neither denial nor completion. Use the Mac terminal if the phone cannot show the native prompt. Keep phone OS notifications off under the privacy setting above. The mobile approval card remains unreliable until a released Orca version passes the paired-app test.
