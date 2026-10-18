# Browser login

Launched Claude Code and Codex workers share one [browser-login procedure](../src/skills/browser-login/SKILL.md). It opens a visible, isolated task browser, controls the intended page without native keyboard focus, and receives credentials through the session's `op`. The operator can inspect the browser before a consequential action.

[Launcher](launcher.md) · [Secret requests](1password-access.md) · [Agent machines](agent-hosts.md) · [Testing](testing.md)

## Route and setup

Choose the browser before entering credentials. Both routes use the same page operations and credential consumer.

| Route | Prerequisites | Use |
|---|---|---|
| Default Orca browser | Running Orca desktop, its CLI and bundled JavaScript runtime | Keep the visible task tab in the worker's workspace |
| Explicit `--browser chrome` | Installed Google Chrome and Node with built-in WebSocket support | Use the machine's browser when Orca is unavailable or cannot render the page |

The Chrome route needs no Orca process or binary. Neither route installs a browser, extension, Playwright package or service. Missing prerequisites are reported. Configure [session op](1password-access.md#set-up-a-machine), then launch a fresh worker. Existing workers retain their delivered skill copies. No model-specific browser flag is required. On a sandboxed Mac, request existing native execution approval for the first browser start.

The portable browser-consumer tests need Node on the CI path. Desktop tests can use Orca's bundled runtime when standalone Node is absent.

```sh
python3 <installed-skill>/scripts/browser.py start https://example.com/
# Alternatively, choose the installed Chrome route:
python3 <installed-skill>/scripts/browser.py start https://example.com/ --browser chrome
python3 <installed-skill>/scripts/browser.py run <state> snapshot -i
python3 <installed-skill>/scripts/browser.py close <state>
```

Keep the returned state path. Expect `BROWSER_READY` at start and `BROWSER_CLOSED` at closure. The [skill](../src/skills/browser-login/SKILL.md#fill-each-inspected-step) owns the inspected fill commands and approval sequence.

## Input without keyboard focus

A conversation-owned tab does not have its own native keyboard. Native text insertion can move focus or deliver input to another active pane. Connecting Playwright through that input path does not establish isolation.

The helper sends values as separate `Runtime.callFunctionOn` arguments to fixed functions on the exact page. It checks HTTPS origin and path, unique visible enabled inputs, input types and an unobstructed submit control. Native input setters and normal input/change events update the form without typing keys or focusing controls. The submit button may initially be disabled. It must become enabled before the helper verifies the values again and clicks it.

## Credential boundary

The session's `op` remains the only secret resolver. Values reach the Python consumer through `op run`, then travel through private standard input and separate protocol arguments. They do not enter shell arguments, page-script source, files or model output. Browser children receive a restricted environment without credentials, tokens, proxy configuration or runtime-injection options. Credential operations return fixed status rather than raw protocol errors.

Username-first, password and generated six- or eight-digit OTP steps share the owned browser. OTP references select `?attribute=otp`. Seeds are refused and leading zeros survive. The [secret-access contract](1password-access.md) owns tier, Home Assistant and operator-ordered desktop access. Each credential step retains its own approval. An approved username request does not approve the later password request. A native permission refusal is distinct from a website refusing credentials.

Full snapshots are refused after the first credential step. Later inspection returns only narrow non-secret properties. No recording, screenshot, HAR or screencast session starts. Normal operator viewing can still display the page. This is not a screen-privacy boundary. CAPTCHA, consent, certificate provisioning, human MFA and magic-link completion are not generic unattended capabilities. An actionable human handoff identifies the service, current step and information the operator needs, then retains the tab only for that agreed intervention.

## Inspection, proof and recovery

Before credentials, `snapshot` describes the page. Use observed text with `click-text`, or a unique CSS selector with `click`. Snapshot references are not CSS selectors. Use `eval` only for narrow read-only expressions. Native typing, keypress and focus commands are not exposed.

`BROWSER_LOGIN_SUBMITTED` proves a click, not authentication. Verify a fresh protected read after the application is ready. A cached dashboard, public shell, email-sent page or completed username stage is not a login pass. Do not expand a read-only task into purchases, messages, account changes or financial actions.

The consumer does not reconnect or retry a credential request. An explicit `phase: preflight`, `credential_input: false`, `submission_attempted: false` refusal permits correcting the setup before a newly approved attempt. Otherwise, use only a narrow read to determine whether a step completed despite a lost reply. Never repeat an uncertain or rejected submission automatically. Read-only inspection errors can be corrected or retried within the skill's bound.

Startup records ownership before navigation, so failed navigation still leaves a recoverable state. Orca cleanup closes only pages in the saved workspace with the exact task profile, then deletes that profile. Chrome cleanup verifies its recorded PID, process start identity, profile argument and private debugging endpoint before closing the owned browser and removing its profile. Neither route adopts the operator's ordinary browser. Unexpected files or uncertain cleanup retain state and must be reported. Orca can retain empty partition files after clearing profile storage.

Chrome's loopback debugging endpoint is a local-user trust boundary, not protection from other processes running as that user. There is no idle cleanup daemon. Close the saved state before worker teardown, then verify absence. An interrupted session can leave its tab open. Browser commands have a thirty-second bound. The protocol consumer has a twenty-five-second deadline. Approval and agreed operator waits are separate from the five-minute active test budget.
