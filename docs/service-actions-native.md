# Native write actions

[Profiles, reads and collection limits](service-actions.md) · [Launcher](launcher.md)

## Write actions

A declared manager may relay only the operator’s exact approval for one named worker and action. Follow the [manager procedure](../src/skills/plot-session/manage.md). Other prompts and workers remain excluded. A relay does not grant permission for another action or change native approval.

`jira-write` and `confluence-write` change Jira and Confluence under the existing service profile's account. Declare either or both in the plot's `service_actions` list. Preparation reuses `jira-read.json` or `confluence-read.json` and derives `action` for the delivered writer; no separate write profile is needed. Shared credentials grant no standing write permission or additional upstream rights. The central `src/native-permissions.toml` contract supplies each action's `needs_intent`, justification and bounded credential exception. Rendering produces the tool policies, and preparation registers one native `run` tool for each selected writer in both clients. The command argument retains the complete fixed consumer command with literal selectors and its private result path. Missing or invalid intent policy refuses delivery. Existing sessions keep their original snapshots.

Each complete command needs explicit conversational approval after its preview read, including arguments and private result path. Approval may refer unambiguously to that command. General requests, read research authority and delivered lists grant no write permission. Claude asks on the named native write tool even under a broad saved allow. Codex tools use `approval_mode = "prompt"`, pinned with the complete delivered server definition in client arguments so a settings reload retains both its command and approval policy. Complete pins precede accepted disable-only overrides. Its configured reviewer checks the full command against the conversation. Writers refuse approval-disabling client arguments and grant no standing write exception. Reads retain their native rules and research authorization. OpenCode has no native writer. Shell, module and standard wrapper invocations refuse delivered writes before credentials. The native adapter checks client identity, approval configuration and its input channel through macOS process APIs or Linux `/proc` and Unix peer credentials. It executes only the fixed consumer and terminates it on cancellation or disconnect. Linux Codex write approval also relies on its shell sandbox blocking native input-pipe access through `/proc`. Run `tests/native/install/test_native_write_tools.py` after a Codex or sandbox change. The Data Center sandbox retains structured invocation.

The delivered consumer admits existing write forms through literal argv and rejects noncanonical write invocations before credentials. Keep the selected absolute Python path and `-E -s -S <absolute-entry> --output <private-result-file>` exactly, then append one form below. Omitted, reordered or combined flags and alternate interpreter or entry paths are refused. The local sandbox keeps its structured-input transport.

```text
jira-write        --permissions PROJECT
                  --create PROJECT --fields JSON_OBJECT_OR_ARRAY_OF_1_TO_3
                  --update KEYS --fields JSON_OBJECT --if-updated UPDATED,...
                  --comment KEYS --body TEXT --if-updated UPDATED,...
                  --transition KEYS --to TRANSITION_NAME --if-updated UPDATED,...
                  --link KEY --type LINK_TYPE --to-issue KEY --if-updated UPDATED,UPDATED
confluence-write  --permissions PAGE_ID
                  --create-page PARENT_ID --pages '[{"title": T, "body": STORAGE}, ...]'
                  --update-page PAGE_IDS --body STORAGE --if-version N,...
                  --comment-page PAGE_IDS --body STORAGE --if-version N,...
```

Each command names at most three tickets or pages, and one payload applies to all of them. More work means more commands, each approved on its own. The preview is a read of the targets plus the exact write command. Every form on an existing target carries the value each target had in that read, Jira's `updated` or the Confluence version number, one per target in target order. Before any write, the consumer reads every target again and refuses the whole command with `CONTENT_CHANGED` if one differs. Jira values compare at whole seconds, because the search behind `jira-read --issues` returns `updated` without milliseconds, so one batch read supplies every guard. A change made in the same second as the change the read saw is not detected. A Confluence update sends the next version number, so the server itself refuses a page that changed in between. Nothing retries.

`--create` takes the form project over `--fields.project`. `issuetype` and fields such as `parent` create sub-tasks or epics. `--transition` requires one available name match or returns `SELECTOR_UNAVAILABLE`. `--link A --type Blocks --to-issue B` means A blocks B. `--update-page` preserves the title. Text and JSON accept 32768 characters with newline and tab, including replacements regardless of existing page size. Hand longer replacements to the operator without browser fallback. A body starting with `--` is refused. Deletion is unsupported.

`--permissions` writes nothing. Jira returns `mypermissions` for the project as a map of permission to true or false. Confluence Data Center reports an account's operations per page, not per space, so its probe returns the page's operations such as `update:page`.

Success is `JIRA_WRITE_PASS` or `CONFLUENCE_WRITE_PASS` with one `written` line per write, naming the target, any created key or ID, the new `updated` or version and the SHA-256 of the exact request body. A write whose new version cannot be read afterwards keeps its line with `version_unconfirmed` naming the failure. A failure after an earlier write in the same command returns `WRITE_INCOMPLETE` with the lines of the writes made and the failing target, and exits nonzero. A failed request with an `HTTP_` code changed nothing. Any other code, such as `REQUEST_TIMEOUT`, leaves that target uncertain, so read it before deciding anything. Record every line in the session notes, since the consumer keeps no record. A mistaken batch is corrected from those lines with new approved writes over the same targets.

## Startup proof

The [native startup preflight](launcher-native.md#native-write-startup) checks required writers before opening a worker, without a model request or service-action call. It is connection proof, not authority to write or proof of upstream credentials. The adapter requires the complete matching server pin and retains its native approval checks. Optional server pins and disable-only choices remain supported.
