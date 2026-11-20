# Browser login

Launched Claude Code and Codex workers use the [browser-login skill](../src/skills/browser-login/SKILL.md). This guide owns setup, architecture and implementation boundaries. The skill owns task scope, commands, credential steps, approvals, human handoffs, verification and cleanup instructions. The [secret-access contract](1password-access.md) owns the session's `op` routes.

[Launcher](launcher.md) · [Agent machines](agent-hosts.md) · [Testing](testing.md)

## Route and setup

The runtime drives a named, persistent Chrome profile for agents through a pinned Playwright command-line tool. It uses a separate Chrome process. Credential input uses a separate consumer on the same connection. It does not pass through the page tool. There is no second browser route.

| Need | Provided by |
|---|---|
| Google Chrome | The operator, once per machine |
| `systemd-run` and `xvfb-run` for the private display on a Linux desktop with no monitor | The machine's packages |
| Node | The machine, see [Agent machines](agent-hosts.md) |
| The pinned page tool | `task browser:install`, once per machine and after a version change |
| A client certificate, where a service requires one | The operator, `task browser:certificate -- <vault> <document item> <url pattern>` in their own terminal. On Linux it imports the certificate and writes Chrome's selection policy. On a Mac the certificate must be in the login keychain, and the task opens a configuration profile with the policy, which the operator installs in System Settings, General, Device Management. Chrome reads this policy on a Mac only from such a profile. The vault's login file names the arguments |

`task browser:install` copies `slopmeister/session/playwright/package.json` and its lockfile to `$XDG_DATA_HOME/slopmeister/playwright/ (default `~/.local/share/slopmeister/playwright/`)` and runs `npm ci --ignore-scripts`. The lockfile pins package versions and integrity hashes. No install script runs. A version change needs a refreshed lockfile, a check that page console messages still leave no log in task state, and a live login, because the attach, the session socket, the session lists and the download folder are Playwright internals.

Configure [session op](1password-access.md#set-up-a-machine), then follow the skill in a fresh launched worker. The [launcher](launcher.md) owns delivery of fixed configuration. Missing machine prerequisites belong to [workstation setup](../src/skills/workstation/SKILL.md).

Chrome asks a person to choose a client certificate, and no agent can answer that prompt, so a service page hangs until someone does. The certificate task therefore also writes Chrome's `AutoSelectCertificateForUrls` policy for that URL pattern. The policy covers every profile on a Linux machine, and on a Mac every Chrome profile of the account that installs it, the operator's own included. The rule has no certificate filter and each run replaces it, so it suits one certificate and one service per machine. The task refuses to run in an agent session. On Linux it reads the private key through real `op` and keeps the file in a private temporary directory only until the import ends.

## Profiles

Each profile is a folder under `~/.local/state/slopmeister/browsers/<name>`. A name has lowercase letters, digits and dashes, at most 32 characters, so it cannot leave that folder. The parent folder and each profile are owner-only, and `start` refuses a profile that is a link, belongs to another user or is readable by others. On a Mac, `tmutil addexclusion` keeps the folder out of Time Machine. The folder is outside every repository and the vault.

The skill passes the plot's name, so each plot has its own sign-ins. A session can name another profile with `--profile`, and a second plot can use the same profile without any plot change. Sign-ins stay in the profile after its Chrome closes.

A new profile copies from the operator's `Default` Chrome profile the `Bookmarks` file, the `Extensions` folder and, of `Preferences` and `Secure Preferences`, only the settings keys for extensions, protection, the browser, the bookmark bar, the search provider, language and spelling. Account, sign-in, sync and Google keys stay behind, and so do cookies, passwords, history and extension storage. A copied password manager therefore starts signed out. A profile that exists is never copied again. With no operator profile, the new profile starts empty.

See [browser profiles at runtime](browser-runtime.md) for tab ownership, downloads, display setup and cleanup.

## Credential and capture boundary

The Python consumer receives resolved values through `op run`. It sends them through private standard input to arguments of a document handle, which runs only in the document it checked, so a redirect never receives a value. Values do not enter child command arguments or page-script source. Browser and page-tool children receive a restricted environment without credentials, proxy configuration or runtime-injection options. Responses use fixed diagnostics rather than raw errors. A fill that fails after input names the helper's own check that stopped it, such as `SUBMIT_UNAVAILABLE`.

The input helper uses native DOM input setters, input and change events and a DOM click. This updates controlled forms without focus or typed keys, and it works on a tab that draws no frames, which happens on a remote desktop. Destination and control checks run before each step's input, so a later step cannot send a value to an unexpected host. Before input, a disabled submit control needs only to be unique and visible, because a disabled button often lets the pointer through to the page behind it. A submit control must become enabled and reachable before its final check and click. The helper repeats that check for up to five seconds, because a page can enable its button from a timer, and Chrome delays timers in a tab it does not draw. A label whose `control` is the exact input counts as that input, because floating labels sit over their field.

Some services put the login form in an embedded frame from another origin, so a step can name one frame. The helper then works only in the one direct child frame at that origin and path, and it refuses none or several. The frame's document checks its own destination, fields and control, as a top-level page does. That document cannot see the top page, so the helper also checks that the tab stays on the step's address and that the top page shows the frame element at the centre of each field and the control. It does these checks before input and again before the click. Deeper frames and page-tool work inside a frame are out of scope.

The pinned page tool saves a snapshot after page actions, and a snapshot shows a filled password. A guard therefore refuses page-tool use while a password or code field in any frame holds a value or a frame does not answer, checks again after each action because Chrome can reveal a saved password, withholds that action's output and deletes its snapshot. The helper clears filled password and code controls after each step, and a filled username once the whole fill ends on every result, because a later page such as Apple's password page can keep that field and need its value. Console capture is disabled because a site can log input independently of the cleared DOM. `run-code` stays refused, because it repeats its code in its output. No recording, trace, network capture or screencast starts.

These guards reduce accidental capture. They do not restrict what arbitrary DOM evaluation could read. The [skill](../src/skills/browser-login/SKILL.md#start-and-work-on-the-page) owns the permitted page commands and DOM-read limits. The runtime allowlist is a transport boundary, not authority for a service change.

## Proof

The [testing guide](testing.md) owns regression commands and evidence conventions. [The skill](../src/skills/browser-login/SKILL.md#verify-and-close) owns live-result verification. Fixtures establish protocol and custody behavior. Real launched workers establish delivery, native approval behavior and service login. Success on one host or service does not establish success on another. Private account facts and service-specific traps belong in the owning vault note.

## Upgrade from task-owned profiles

Close active states using the worker that opened them. Start a fresh worker after upgrading. Choose its profile at the first sign-in. Previous Chrome sessions and saved profiles stay on disk.
