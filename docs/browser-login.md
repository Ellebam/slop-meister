# Browser login

Launched Claude Code and Codex workers use the [browser-login skill](../src/skills/browser-login/SKILL.md). This guide owns setup, architecture and implementation boundaries. The skill owns task scope, commands, credential steps, approvals, human handoffs, verification and cleanup instructions. The [secret-access contract](1password-access.md) owns the session's `op` routes.

[Launcher](launcher.md) · [Agent machines](agent-hosts.md) · [Testing](testing.md)

## Route and setup

The runtime drives the operator's own Chrome through Microsoft's [Playwright Extension](https://chromewebstore.google.com/detail/playwright-extension/mmlmfjhmonkocbjadbfplnigmagldckm) and a pinned Playwright command-line tool. Credential input uses a separate consumer on the same connection. It does not pass through the page tool. There is no second browser route.

| Need | Provided by |
|---|---|
| Google Chrome with the Playwright Extension, running in a desktop session | The operator, once per machine, because Chrome requires a person to confirm the install |
| Node | The machine, see [Agent machines](agent-hosts.md) |
| The pinned page tool | `task browser:install`, once per machine and after a version change |
| A client certificate, where a service requires one | The operator, `task browser:certificate -- <vault> <document item> <url pattern>` in their own terminal on Linux, or Keychain Access on a Mac. The vault's login file names the arguments |
| The extension token as a 1Password item in an explicitly selected vault | The operator. The token belongs to one Chrome profile and stays valid until `Generate new token` |

`task browser:install` copies `slopmeister/session/playwright/package.json` and its lockfile to `$XDG_DATA_HOME/slopmeister/playwright`, defaulting to `~/.local/share/slopmeister/playwright/`, and runs `npm ci --ignore-scripts`. The lockfile pins package versions and integrity hashes. No install script runs. A version change needs a refreshed lockfile, a check that page console messages still leave no log in task state, and a live login, because the extension relay and the session socket are Playwright internals.

Configure [session op](1password-access.md#set-up-a-machine), then follow the skill in a fresh launched worker. The [launcher](launcher.md) owns delivery of fixed configuration. Missing machine prerequisites belong to [workstation setup](../src/skills/workstation/SKILL.md).

Chrome asks a person to choose a client certificate, and no agent can answer that prompt, so a service page hangs until someone does. The certificate task therefore also writes Chrome's `AutoSelectCertificateForUrls` policy for that URL pattern. The rule has no certificate filter and each run replaces it, so it suits one certificate and one service per machine. The task reads the private key through real `op`, so it refuses to run in an agent session, and it keeps the file in a private temporary directory only until the import ends.

## Why the operator's Chrome

The operator can reuse an existing signed-in service through the same shell route on both tools. The extension token removes the interactive connection choice. A consumer under `op run` keeps resolved credentials away from the model.

## Trust boundary

The extension token gives its holder full control of the operator's Chrome. The extension's own warning says a connection exposes the entire browser, including sessions, cookies and other tabs. Tab groups organize work and are no security limit. The operator chooses the vault and its tier during setup. Resolve the token through that tier's normal approval route. Regenerate it after a suspected leak, update 1Password and restart Chrome.

Playwright passes the token in the address of the extension's connect tab. `start` discards attach output, deletes the automatic snapshots, opens its own tab and closes the connect tab before returning. `run` redacts extension addresses from every output. The session socket lives in the owner-only state. The page tool uses the real home to find Chrome, so `PWTEST_CLI_GLOBAL_CONFIG` replaces its global settings, which could otherwise redirect it to another browser.

## Credential and capture boundary

The Python consumer receives resolved values through `op run`. It sends them through private standard input to arguments of a document handle, which runs only in the document it checked, so a redirect never receives a value. Values do not enter child command arguments or page-script source. Browser and page-tool children receive a restricted environment without credentials, proxy configuration or runtime-injection options. Responses use fixed diagnostics rather than raw errors.

The input helper uses native DOM input setters, input and change events and a DOM click. This updates controlled forms without focus or typed keys, and it works on a tab that draws no frames, which happens on a remote desktop. Destination and control checks run before each step's input, so a later step cannot send a value to an unexpected host. A submit control must become enabled before its final check and click. A label whose `control` is the exact input counts as that input, because floating labels sit over their field.

The pinned page tool saves a snapshot after page actions. That snapshot can show a filled password. Before each action, a guard checks every frame. It refuses page-tool use if a password or code field holds a value, or if a frame does not answer.

The guard checks again after each action because Chrome can reveal a saved password. If that check fails, the runtime withholds the action's output and deletes its snapshot. The helper clears filled controls after each credential step.

Console capture is disabled because a site can log input even after the helper clears the fields. `run-code` stays refused because it repeats its code in its output. No recording, trace, network capture or screencast starts.

These guards reduce accidental capture. They do not restrict what arbitrary DOM evaluation could read. The [skill](../src/skills/browser-login/SKILL.md#start-and-work-on-the-page) owns the permitted page commands and DOM-read limits. The runtime allowlist is a transport boundary, not authority for a service change.

## Other extensions in the tab

Chrome removes an extension's debugger from any tab that holds a frame of another extension, and it refuses to reattach while the frame exists. The relay reports this as a closed page. The page tool then opens a blank tab for its next command, while the real tab stays open outside the session. This is the design limit of driving Chrome through an extension, and only an agent-only profile would remove it.

1Password adds such frames to login pages, only while it is unlocked and holds a login for the site. The runtime therefore loads a short init script in every task tab. It registers `com-1password-menu`, `-uso`, `-notification` and `-modal` as custom elements with shadow roots disabled, so 1Password's `attachShadow` call throws and no frame appears. The script runs in the page, and its effect reaches 1Password's isolated world. A person who takes over a task tab gets no 1Password prompt there. Proof that the route survives needs 1Password unlocked on a site with a stored login, because a locked 1Password hides this fault. After a 1Password update, check that the names still match.

If a frame still arrives, the guard returns `BROWSER_TAB_LOST`, `start` returns `BROWSER_PAGE_NOT_REACHED` and `close` names the tab in `tabs_left`, because the route has no way to reach a tab it lost. `check` runs before `op tier-two`, because approval comes before the entry starts. Chrome's `extensions-on-extension-urls` switch stays off. It would open 1Password's frames to every session that holds the token.

## Proof

The [testing guide](testing.md) owns regression commands and evidence conventions. [The skill](../src/skills/browser-login/SKILL.md#verify-and-close) owns live-result verification. Fixtures establish protocol and custody behavior. Real launched workers establish delivery, native approval behavior and service login. Success on one host or service does not establish success on another. Private account facts and service-specific traps belong in the owning vault note.

## Upgrade from task-owned profiles

Close old browser states with the old delivered entry before replacing their worker. New workers use only the extension route. The old `--browser`, `--persistent`, `page` and `clear-profile` commands are removed. Use `run` for page commands and `--step` for inspected credential pages. Existing saved profiles are not imported, modified or deleted. Retire an old profile separately only on the operator's order after its browser has exited.
