# Browser profiles at runtime

[Browser login and setup](browser-login.md)

## One Chrome per profile

The first `start` of a profile opens that profile's Chrome as a page tool session named `keep`, with `open --persistent --profile=<folder> --browser=chrome --headed`. The page tool starts Chrome with `--remote-debugging-pipe`, so Chrome opens no network port. Each state then attaches to `keep` as a page tool session of its own and makes its own tab with `tab-new`. Every page tool call of a profile shares that profile's owner-only runtime folder, `/tmp/sm-browser-<uid>/<name>`, which holds the session sockets, the session list and a lock file. Two profiles never see each other's sessions. The folder path is short because socket paths have a length limit.

A lock file serializes the start and close of one profile, so a close never ends Chrome under a new start. `close` closes this state's tabs and detaches its session. When `list` then shows no other attached session, it also closes `keep` and stops the private display. A start that fails runs the same teardown, so a failed second start leaves a live peer's Chrome alone. It first deletes the state's page tool files, because a failed attach or tab output can name another session's page.

A tab is this session's own when its Chrome target is the one `start` recorded, or when its chain of openers leads to that target. The page tool's current tab can move to another session's tab, for example when a popup closes itself. The guard therefore checks before and after each command that the current tab is an own tab. When the check fails after a command, it withholds the output, deletes the snapshot and says the command may have reached another session's page. The tab commands read no page and skip that check, so a session can always find its own tab again. Every reply loses the page tool's list of all open tabs, and `tab-list` shows only own tabs, because another plot's page titles can be field facts. `tab-select` reaches only own tabs. `tab-close` goes through the helper by target, never by the page tool's index, so a shifted index cannot close a peer's tab. Ref-based commands are bound to the page they were read from. A key press or navigation in the short time between the two checks stays a known risk.

Background windows keep drawing while the profile is running.

## Trust boundary

Any process of the operator's user can drive a profile's Chrome through its owner-only socket, as it can read the profile folder. There is no token, extension or port. `run` cuts every page and link address at its query or fragment, because these can carry an account name or a sign-in flow value. A snapshot file the page tool saves keeps its link addresses whole. The cut scans each run of address characters once, so a hostile page cannot slow it down. The page tool uses the real home to find Chrome, so `PWTEST_CLI_GLOBAL_CONFIG` replaces its global settings, which could otherwise redirect it to another browser.

The page tool saves each download into the state's `playwright/.playwright-cli` folder, not into `~/Downloads`. Close deletes it with the state. Each session attached to the profile saves its own copy of a download, and its own close deletes that copy.

## Private display

On a Linux desktop with no monitor, a Chrome started there opens no window and the start hangs. `start` detects that case before it launches anything, when the profile's Chrome is not yet running. With `--private-display`, it starts one transient systemd user unit per profile, `slopmeister-browser-<name>`, which runs `xvfb-run` without TCP listening and with its auth file in the profile's owner-only runtime folder. It waits until the display reports its number and its X socket exists, then starts the profile's Chrome in it. The last `close` stops the unit even when Chrome did not close, and keeps the state when the stop is not confirmed. The unit has a 30-minute runtime limit, for a state that is never closed. Other states of the profile use that display until then.
