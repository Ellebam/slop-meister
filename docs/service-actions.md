# Selected service actions

A plot can declare fixed read and write actions whose complete execution requires native approval review after the operator authorizes the action. Codex uses Approve for me. Claude keeps its explicit action ask. Slopmeister delivers the consumer and its non-secret profile into a new session. These actions retain this route independently of the [two-tier secret route](1password-access.md). No Home Assistant decision or desktop prompt is added.

## Declare and provision

Add `service_actions = ["jira-read", "confluence-read"]` to the selected plot's `[target]` table. An omitted or empty list delivers no action code, profile or prompt rule. Unknown actions fail delivery. Adding another integration requires an explicit plot/action declaration and a checked-in consumer, not an arbitrary command or URL argument.

Each service has one machine-local connection profile, `~/.config/slopmeister/access/<plot>/jira-read.json` or `confluence-read.json`, owned by the operator with mode `0600`. Reads and selected writes reuse its routing, expected identity and credential references. Delivery derives the declared action and removes read-only query settings for a writer. Field vault notes own the access facts and secret references; the profile is validated runtime input, never credential values or write authority. Keep it outside Slopmeister and the vault's shared document files.

```json
{
  "action": "jira-read",
  "plot": "example",
  "origin": "https://jira.example.invalid",
  "expected_user": "reader",
  "account_id": "AAAAAAAAAAAAAAAAAAAAAAAAAA",
  "vault_id": "bbbbbbbbbbbbbbbbbbbbbbbbbb",
  "vault_name": "Automation",
  "pat_ref": "op://Automation/JIRA_PAT/credential",
  "password_ref": "op://Automation/CLIENT_CERT/password",
  "certificate_document": "CLIENT_CERT",
  "token_file": "/Users/operator/.config/slopmeister/credentials/slopmeister.env"
}
```

The `origin` field accepts an HTTPS base URL with an optional application path, such as `https://atlassian.example.invalid/jira` or `/confluence` on that same host. Path segments accept letters, digits, hyphens and underscores. API requests and returned links preserve that prefix. Queries, fragments, dot segments and encoded paths are rejected.

For PAT-only HTTPS, omit both `password_ref` and `certificate_document`. Supplying only one is invalid. When both are present, the existing in-memory client-certificate flow is retained. Omitting them skips certificate and certificate-password retrieval entirely and still uses normal server TLS verification.

The optional `server_ca` field names an absolute path to a PEM certificate. The request then trusts only that certificate for the origin instead of the system trust store. The supervisor refuses it unless it is a regular file owned by the operator, reached without symlinks and not writable by group or others. Keep it in a private `0700` directory like the token file, because the supervisor does not check the directories above it. Linux curl uses OpenSSL with an empty CA directory. macOS uses SecureTransport for pinned PAT-only requests and refuses a pin with a client certificate before credentials are read. Field profiles omit it. The [Atlassian sandbox](atlassian-sandbox.md) uses it for its per-machine `localhost` certificate.

The token file is an owned regular `0600` file in a private `0700` directory. It contains one `OP_SERVICE_ACCOUNT_TOKEN` assignment followed by a newline. Provision it through an operator-authorized secret-entry path. Do not print it, put it in Git or iCloud, link it into a repository, copy it into worktrees, or export it in shell startup files. The consumer reads it directly only after native action approval. Directory sessions use the same location.

The service account must have read access to exactly the selected vault. This is vault-wide access, not per-item authorization. Keep its expiry and rotation policy explicit. An absent, revoked or expired token fails without desktop fallback. Rotation means replacing the protected file through the approved secret-entry path and revoking the old token in 1Password. Removing a plot declaration prevents new delivery but does not revoke an existing snapshot or token. Revoke upstream access when immediate removal is needed.

The Atlassian actions use fixed Python 3.14, `op` and curl paths from `slopmeister/session/service_actions/constants.py`. Admission checks executables, HTTPS and PKCS#12 before credentials. Curl uses SecureTransport on macOS or OpenSSL on Linux. Linux certificate profiles also require `/usr/bin/openssl` with active default and legacy providers. The supervisor probes the delivered provider with empty input and no credentials. `LOCAL_PREREQUISITE_MISSING` means no provider contact. A missing `provider module` means the probe failed. The provider checks its interpreter and runs in its delivered reader directory. Repair the prerequisite and start a fresh session.

`NATIVE_APPROVAL_REQUIRED` can be a local fault before provider contact. Reasons are `client` (client-path mismatch), `ask` (missing native write approval rule) and `local` (other local faults). Repair the setup and start a fresh admitted session. Do not bypass refusal by changing arguments or using a browser.

The fixed entry and standard-library implementation under `slopmeister/session/service_actions/` are copied byte for byte into read-only action trees and recorded in the session-source manifest. Each service-account CLI call sets `OP_BIOMETRIC_UNLOCK_ENABLED=false` and `XDG_CONFIG_HOME` to the operator's `~/.config`. On macOS it sets `HOME=/var/empty` to avoid the desktop app's protected-container check and [app-data prompt](1password.md#macos-app-data-consent). Linux keeps the operator's home. Both use only the service-account token, without desktop fallback. Launch a fresh session through the [plot launcher](session-walkthrough.md) to receive consumer changes. Existing snapshots are retained. A changed plot action selection prevents redispatch into its older workspaces.

## Run the action

Verify operator authorization for the complete fixed read. Create its private result directory and file before submission:

```bash
# macOS
/usr/bin/mktemp -d /private/tmp/slopmeister-read.XXXXXXXX
# Linux
/usr/bin/mktemp -d /tmp/slopmeister-read.XXXXXXXX
/usr/bin/mktemp <returned-directory>/result.XXXXXXXX
```

Use the returned absolute paths. On Linux use the selected Python path. Request native review of the selected tool's absolute delivered entry with `--output` set to that precreated result file. Do not use shell redirection because it bypasses the native command rule. Set a native tool timeout of at least 330 seconds:

```bash
# Codex
/opt/homebrew/bin/python3 -E -s -S <workspace>/.codex/service-actions/jira-read/entry.py --output <private-result-file> --find --assignee me

# Claude Code
/opt/homebrew/bin/python3 -E -s -S <workspace>/.claude/service-actions/jira-read/entry.py --output <private-result-file> --find --assignee me
```

Both tools route the exact absolute entry through native review. Codex's automatic reviewer may approve without a human prompt. Claude keeps its explicit ask. Do not save a session-wide exception or alter delivered code. The delivered instructions identify the consumer revision. Native protection and snapshot validation guard ordinary edits, not a hostile process with the same local account.

Claude's Edit deny rules use absolute workspace paths for both delivered action directories. The launcher passes these rules through an explicit settings file, where a single leading slash would anchor them at that file's directory. Edit rules also cover the native Write tool.

Both tools receive read-only action files (`0444`), owner-readable private profiles (`0400`) and read-only action directories (`0555`). This blocks ordinary patch, edit and file-creation attempts independently of command sandboxing. The existing installer snapshot detects changes to content or permissions. These modes do not prevent the local owner from deliberately changing permissions. Preserve existing snapshots and start a fresh session to receive a changed consumer. Remove an explicitly retired workspace through the [supported removal command](workspace-removal.md).

The fixed entry passes raw argv to the supervisor without Task template expansion. Use only its absolute command, never a cwd-relative Python module call. The native rules bind review to that entry; they remain secondary guardrails, not isolation against a hostile process with the same local account.

If the native command returns a running session, collect that same session until it finishes. Never submit the action again to recover a lost response. Accept success only after native exit `0`, an owned regular `0600` result file, complete valid JSON with the expected `JIRA_CONTEXT_PASS` or `CONFLUENCE_FETCH_PASS` code, and no output beyond the consumer's 2 MiB limit. A nonzero or uncertain exit is not success even when the file contains data. Keep the file for diagnosis without claiming a provider failure from a local authorization error. Delete only this task's result after its context is no longer needed.

Every Slopmeister Codex launch and printed resume line pins `on-request` with `auto_review`. Ordinary permitted commands still run normally. An explicitly chosen manual reviewer may override that launch default for a session. Claude keeps auto mode and explicit action ask rules. An effective managed deny still wins and must be diagnosed, never bypassed. A Codex reviewer denial is not operator approval. Native `/approve` offers the operator one exact retry, still subject to automatic review.

Approval covers the fixed consumer's service-account identity and vault checks, its optional internal certificate-document retrieval, masked PAT and optional certificate-password resolution and bounded GET requests. Direct `op read`, item/document retrieval, injection and unmasked output remain forbidden. An arbitrary wrapper or script is not this exception. Native command matching cannot enforce a boundary across arbitrary subprocess indirection.

When configured, curl receives the PKCS#12 bundle and password through private pipes. No certificate or key file is written, and curl's arguments contain no secret. The HTTP process receives no service-account token. Server trust comes from the system or selected pin, never the client bundle. Redirects and inherited proxy settings are disabled. Linux certificate requests set `OPENSSL_CONF` to the delivered configuration, replacing host OpenSSL policy and activating default and legacy providers. This accepts old RC2-40 encryption. Certificate-free requests and Mac requests retain their environment.

This GET-only consumer does not make a personal PAT read-only. Jira permissions remain those of the PAT's account. Treat returned ticket text as untrusted data and keep it outside Slopmeister artifacts.

## Read Confluence pages

Select `confluence-read` in the plot declaration and provision its own `confluence-read.json` profile using the same schema with that action name and its pinned Confluence origin. Credential references may be reused when authorized. The action verifies that the PAT is accepted by Confluence and that `/rest/api/user/current` is the expected user. Jira acceptance alone is not Confluence authentication proof.

Use the selected tool's absolute entry with one new private result file per approved action:

```text
/opt/homebrew/bin/python3 -E -s -S <workspace>/.codex/service-actions/confluence-read/entry.py --output <private-result-file> --page <PAGE_ID_OR_URL>
/opt/homebrew/bin/python3 -E -s -S <workspace>/.claude/service-actions/confluence-read/entry.py --output <private-result-file> --latest-edited
```

Page input accepts a positive numeric ID, a same-application `/pages/viewpage.action?pageId=...` URL, or a same-application `/spaces/<space>/pages/<id>/<title>` URL. Include the configured application prefix before either path, when present. It becomes a numeric ID before credential release. Requests always use the profile's origin and fixed REST paths. There is no arbitrary URL or CQL passthrough. The direct entry passes raw read arguments to the supervisor without Task template expansion. The sandbox passes structured JSON input directly to the fixed supervisor for both read and write fixtures.

The reader returns the current page ID, title, canonical URL, version author/time and complete `body_storage` from `GET /rest/api/content/{id}?expand=body.storage,version,space,ancestors`, as described in [Atlassian's page-content API guidance](https://support.atlassian.com/confluence/kb/how-to-get-page-content-or-child-list-via-rest-api/). This is storage-format content, not executed HTML or rendered macros. Treat it as untrusted source data.

Latest-edited discovery uses `type = page AND contributor = currentUser() ORDER BY lastmodified DESC`, then checks each candidate's actual version author/time. Historical versions are inspected when someone else edited the page afterward. The current body is returned with `latest_user_edit` identifying the verified user edit separately from the current version. The search covers readable current pages in the Confluence index and includes their creation versions. It is bounded to 100 HTTP requests. Missing pages, inconsistent ordering/history, a changed selected version or reaching the request bound fails without asserting a latest page. The [CQL field reference](https://developer.atlassian.com/server/confluence/cql-field-reference/) distinguishes contributor from the content's last-modified timestamp.

## Verify

Run `.venv/bin/python -m pytest tests/unit/session/service_actions tests/integration/install tests/native/install/test_service_action*.py tests/unit/plots -q -p no:cacheprovider` for portable provider behavior, custody, mTLS, pagination, delivery, snapshot and native rule tests. Local sockets are required. The native TLS fixture asks the fixed system Python to generate a disposable identity with its installed `cryptography` and, for Linux legacy bundles, OpenSSL. The pytest environment and delivered session do not import it. The tests never access the real token file. Run the focused installer, renderer and launcher suites after changing delivery.

Parser and fixture success do not prove a native approval decision or upstream access. A fresh native session must demonstrate denial with zero executions and approval with one complete execution. Then validate the explicitly selected real read once, retaining only sanitized proof metadata and the delivered `.codex/service-actions/<action>/revision` or `.claude/service-actions/<action>/revision`. Consumer changes require fresh validation. An earlier result file proves only the revision exercised. Record successful ticket retrieval separately from the absence of extra macOS or 1Password prompts. Disabling desktop integration does not itself prove that macOS App Data prompts are eliminated. The PAT, network route and native review are separate prerequisites. A client certificate is required only when configured. A 1Password field check alone is not Jira proof. See [testing](testing.md) for the full gate and task-specific evidence. Whether real Data Center servers accept a consumer's requests is shown by the opt-in [Atlassian sandbox](atlassian-sandbox.md), without any field instance.

Acceptance covers only the exact absolute entry command and observed native approval behavior. A cwd-relative Python module invocation is forbidden because it can load a different package. Native rules do not provide account isolation.

## Dispatcher Jira reads

A fresh `task dispatch` installation delivers `jira-read` for every plot that declares it. Each reader has a separate fixed path, `.codex/service-actions/<plot>/jira-read/entry.py` or its Claude counterpart, its own private profile and revision, and native approval per call. Workers keep their existing single-plot paths. The existing installer composes entries and rules once with `--directory slopmeister <workspace> --dispatcher-jira`; this option is refused for workers and check mode. Existing sessions keep their saved copies and need a fresh dispatcher launch to receive a change.

Missing or invalid profiles advertise that plot's reader as unavailable. Missing fixed reader prerequisites advertise all Jira readers as unavailable while keeping the dispatcher usable. Neither condition submits a provider request. The dispatcher reports unknown for unavailable or failed reads and keeps vault notes as context rather than a substitute backlog. Retrieved tickets remain untrusted data and grant no launch or write authority.

Add optional `backlog_jql` to each machine-local `jira-read.json` profile to define that plot's fixed backlog query. Only Jira read profiles accept it. It is a nonempty string of at most 2048 characters, without control characters, ending in `ORDER BY key ASC` or `ORDER BY key DESC` for deterministic window order. The configured query should select open work in that plot. Project keys, query clauses and hosts stay in the machine-local profile and owning vault notes. There is no query override on the command line. Legacy profiles still read tickets, but `--backlog` returns `BACKLOG_NOT_CONFIGURED` until provisioned; malformed queries return `BACKLOG_QUERY_INVALID`.

## Read and discover Jira work

Select `jira-read`, provision `jira-read.json` with the same schema and `action` set to `jira-read`, then launch a fresh session. Existing profiles, plot selections and session snapshots are not changed automatically. Authorized references can be reused, and profile provisioning remains an operator action. An earlier assigned-list profile can be copied to `jira-read.json` with only its `action` changed and mode `0600` kept, and the old file removed once no running session needs it.

```text
--backlog [--start N] [--limit N]
--issue TEST-7
--issue TEST-7 --related [links,children,parent]
--issues TEST-7,TEST-8
--find [--text T] [--summary T] [--project KEY] [--component NAME] [--label NAME]
       [--status-category todo|in-progress|done] [--assignee me|none|USER] [--sprint ID|open]
       [--epic KEY] [--parent KEY] [--board ID] [--filter ID] [--keys KEY,...] [--linked-to KEY]
       [--order updated|created|priority|rank|key] [--start N] [--limit N]
--projects | --boards [--project KEY] [--name T] | --sprints BOARD_ID [--state active|future|closed]
```

Append one form after the entry path. Each form and option is declared once in `slopmeister/session/service_actions/jira.py`, then validated in the supervisor before credential resolution and again in the provider before HTTP. A refused selector names the option and what it expects, never the supplied value. There is no JQL, URL or field-list passthrough.

`--backlog` uses the profile query through the same GET search, candidate projection and pagination as discovery. It requests no ticket bodies or custom-field discovery. The profile query is checked before credential resolution and again before provider HTTP. Each continuation is a separate approved call. The dispatcher distinguishes available, blocked and unknown from the returned link direction and status category, retaining unknown when link/status evidence or relationship semantics are unavailable.

`--issue` requests `/rest/api/2/issue/{key}?fields=*all&expand=names,schema`, its remote links and every visible comment page. `JIRA_CONTEXT_PASS` contains `issue.fields`, `issue.names`, `issue.schema`, `issue.remote_links` and `coverage`. Exposed values are preserved, issue links keep their inward/outward structures, and unmapped fields and missing metadata are explicit. Worklogs retain only embedded entries with coverage, attachments are metadata only, and changelog is not fetched. A narrow final identity/update check detects some changes, not an atomic snapshot.

`--related` adds one hop of neighbours with complete bodies: both link directions, parent, epic, parent link, subtasks and epic children. Relations the instance cannot resolve are listed as not searched. More than 50 neighbours fails with `RELATED_LIMIT`. `--issues` reads 1 to 50 known keys through one key search with names and schema once, and fails if Jira returns fewer than its reported total. Both list keys the account could not read in `not_returned`. Batch reads complete embedded comments only when the embedded set is short, and they are not snapshots.

`--find` combines typed filters into fixed JQL. Text, names and keys are escaped into string literals. Status categories use their IDs and Sprint, Epic Link, Parent Link and Rank clauses use `cf[id]` resolved from `/rest/api/2/field` by schema type, so localized field names do not matter. An explicit filter or order that does not resolve to exactly one field or board filter fails with `SELECTOR_UNAVAILABLE` instead of running a wider search. Results are candidate metadata, including `status_category` and raw `issuelinks`. Absent links remain null, distinct from an empty list. Link type/direction and the embedded linked ticket status are preserved for blockers outside the query as well. `--projects`, `--boards` and `--sprints` list the IDs other forms take, the latter two through the Jira Software agile API where the instance provides it.

Listing forms return `pagination` with numeric `start`, `limit`, `returned`, `has_more`, `next_start` and `total`. Board and sprint listings report `total` as null and page by Jira's last-page flag. Contradicting totals, short pages with more remaining, duplicates and mismatched starts fail with `RESPONSE_INVALID`. Returned next URLs are never followed. Windows can shift between runs. Results cover only what the account can see, and no result does not prove absence.

## Explore Confluence

The existing `confluence-read` profile also supports these operations after fresh delivery:

```text
--search "release procedure" --space TEST
--title "release" --space TEST
--spaces
--pages-in-space TEST
--children 123
```

Append one form after the entry path, as with `--page`. Text/title search optionally restricts a space and searches readable current pages regardless of author. Search is indexed term matching, not a substring scan; no result is not proof of absence. Plain input is escaped into fixed CQL clauses. Arbitrary CQL and arbitrary URLs are unsupported. Space keys accept ordinary keys and personal-space keys, with dot segments, traversal, controls and ambiguous flag values rejected.

Search and listing forms accept `--start N` and `--limit N`, defaulting to zero and 25, with a maximum limit of 100. `CONFLUENCE_FETCH_PASS` includes `operation`, candidate `results`, `pagination` and `coverage`. Page candidates list absent `space` and `version` fields in `metadata_not_returned`, distinguishing omitted metadata from an explicitly returned null. `pagination.has_more` and `next_start` identify another result window, using the same operation and filters. Returned next URLs are never followed. An upstream total that is unavailable stays null. A supplied total that contradicts continuation metadata fails with `RESPONSE_INVALID`. Listing results are not a complete research result or complete page bodies. Separate windows can observe changing upstream content.

Current page reads, including the page selected by latest-edited discovery, include storage body, version, space and ancestors where exposed, all visible comment/reply pages and all attachment metadata pages. Anonymous author metadata is preserved as supplied. Missing metadata is explicit. Comments request all depths and exposed locations, including inline/resolved comments where supported by the deployed API. The request explicitly expands `extensions.inlineProperties` and `extensions.resolution` to preserve anchor and resolution context. Comment coverage lists per-comment `metadata_not_returned` if those requested properties are omitted. Collection completeness describes pagination, not proof that omitted metadata is absent upstream. Macros and included pages remain unexpanded source references; retrieve relevant pages separately within the approved research scope. Binary attachments and historical page bodies are not returned. Latest-edited still reads historical version metadata only to identify the user's latest edit.

## Write actions

`jira-write` and `confluence-write` change Jira and Confluence under the existing service profile's account. Declare either or both in the plot's `service_actions` list. Preparation reuses `jira-read.json` or `confluence-read.json` and derives `action` for the delivered writer; no separate write profile is needed. Shared credentials grant no standing write permission or additional upstream rights. The central `src/permissions.toml` contract supplies each action's `needs_intent`, justification and bounded credential exception. Rendering produces the tool policies, and preparation registers one native `run` tool for each selected writer in both clients. The command argument retains the complete fixed consumer command with literal selectors and its private result path. Missing or invalid intent policy refuses delivery. Existing sessions keep their original snapshots.

Each complete command needs explicit conversational approval after its preview read, including arguments and private result path. Approval may refer unambiguously to that command. General requests, read research authority and delivered lists grant no write permission. Claude asks on the named native write tool even under a broad saved allow. Codex tools use `approval_mode = "prompt"`, pinned in client arguments so home configuration cannot override it when project configuration is untrusted. Its configured reviewer checks the full command against the conversation. Writers refuse approval-disabling client arguments and grant no standing write exception. Reads retain their native rules and research authorization. OpenCode has no native writer. Shell, module and standard wrapper invocations refuse delivered writes before credentials. The native adapter checks client identity, approval configuration and its input channel through macOS process APIs or Linux `/proc` and Unix peer credentials. It executes only the fixed consumer and terminates it on cancellation or disconnect. Linux Codex write approval also relies on its shell sandbox blocking native input-pipe access through `/proc`. Run `tests/native/install/test_native_write_tools.py` after a Codex or sandbox change. The Data Center sandbox retains structured invocation.

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

## Limits, collection and research permission

Every read permits at most 100 HTTP requests, 25 seconds per request and 300 seconds total execution including credential setup. Pre-execution native approval time is outside that budget. Each provider response and the final serialized UTF-8 JSON result, including its newline, is limited to 2097152 bytes. Final emission escapes transport-sensitive control characters and uses compact JSON. Optional certificate and credential input limits remain unchanged. Required-collection failures, invalid pagination, duplicates, changed totals, detected content changes, timeouts and size limits produce bounded failures, never clipped success.

The private result file is distinct from the native tool's display limit. Inspect its ownership, mode and byte count, then record the SHA-256 without printing its contents:

```bash
# macOS
/usr/bin/stat -f '%Su %Lp %z' <private-result-file>
# Linux
/usr/bin/stat -c '%U %a %s' <private-result-file>
/usr/bin/shasum -a 256 <private-result-file>
```

Read bounded text from that same file by Unicode character offset, advancing through every chunk without gaps. For example, the command below prints at most 1024 characters from offset `0`; use each next offset until the file's full character length is covered:

```bash
python3 -c 'from pathlib import Path; import sys; s = Path(sys.argv[1]).read_text(encoding="utf-8"); n = int(sys.argv[2]); print(s[n:n + 1024], end="")' <private-result-file> 0
```

Check the same file size and SHA-256 again after collection, then parse the complete UTF-8 JSON and verify its result and coverage. Reading it consumes no new provider action or research budget. If the native command's exit or file identity is uncertain, preserve the file and report unknown rather than submit another read.

When authorization is missing, Jira and Confluence research requests name the objective, project, board, ticket, space or page-tree boundary, maximum body reads and maximum discovery calls. Agents choose useful next reads inside that approved scope. New submissions, including search continuation, consume the appropriate budget; reading an existing result file does not. Request new permission before extending scope or exhausting budgets. Existing sufficient authorization is reused. Native approval still applies to each submitted action. No new batch executor, background crawler or identity fallback is introduced.

Run `.venv/bin/python -m pytest -q tests/unit/session/service_actions tests/integration/install/test_service_actions_*.py tests/integration/install/test_native_write_lifecycle.py tests/native/install/test_service_action*.py tests/native/install/test_native_write*.py tests/unit/plots`. These cases use synthetic profiles, fake `op`, disposable HTTPS providers and delivered consumer copies. They prove the bounded consumer, real curl TLS, actual client approval/refusal, parent-owned input channels and writer cleanup under scripted decisions. They do not prove a production model's judgment or current customer permissions. Validate real provider access separately only when authorized, and approve each write's complete command.
