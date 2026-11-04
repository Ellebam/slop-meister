# Releases

## Upgrading to 0.5.0

Start fresh workers for the changed fixed instructions. The independent diff check now runs the test guide in a clean copy. It replaces the separate tester command. Rinse replaces leak-check for outward drafts. Night mode requires an explicit bounded operator grant.

Selected Jira and Confluence reads run as one allowed command and return a private result-file path. Writes retain their exact-command native approval. The local Atlassian sandbox is removed. Before upgrading an existing sandbox installation, use its previous reviewed version to stop or remove its resources under an explicit operator order. The update does not delete containers, credentials or retained data.

Browser login now uses the operator’s Chrome through the Playwright Extension. Follow [browser setup and migration](browser-login.md). Existing task profiles are not adopted or deleted. The optional Linux certificate-import command is operator-only.

The retired slot `setup_files` and `disposable` declarations must be removed from local plot definitions. Setup commands remain supported. Public cleanup continues to protect unknown ignored work and uncommitted changes. Unfinished harvest keeps the workspace and claim. Vault notes are checked before editing and committed by name immediately after each edit.

The optional host layer pins Home Assistant 2026.10.2. Deploy the host services separately after reviewing their configuration.

## Upgrading to 0.4.0

Start fresh workers to receive the updated fixed configuration. Harvest replaces the finalize and close-out procedures and accepts an operator order in ordinary words. Sessions no longer create automatic retro records. Existing notes and explicit legacy-log commands remain available. Follow-up pull requests retain their predecessor link and retry safely. Managers can relay only the exact operator-ordered worker approval. Terminal sends require operator intent.

The `update-prs` skill and `slopmeister-vault retro-count` command are removed with no replacement.

Bloom creates one decision page for three or more open operator choices and verifies pages in an isolated headless browser. Authorized sign-ins can use an existing generated one-time code through the protected consumer. Task-owned loopback fixture factors remain separate from real account MFA. Keep codes and seeds out of output.

The [host boundaries](../host/README.md#public-host-boundaries) describe the minimal approval and page services. Deploy these services separately with a reviewed revision.

## Upgrading to 0.3.0

Update the Home Assistant approval route before upgrading workstation requesters. The requester now requires an explicit receipt from the server. Follow the [approval protocol and setup](1password-access.md) for the update order.

Existing workers retain their fixed configuration. Start a fresh workspace to receive the updated instructions, as described in [Updates](../README.md#updates-and-limits). Persistent browser authentication was optional in this version. See the current [browser migration](browser-login.md#upgrade-from-task-owned-profiles) before upgrading further. New [session retros](vault-version-control.md#session-retros-and-legacy-logs) use separate notes, while explicit legacy-log commands and public path overrides remain available. Existing logs are not migrated automatically.

## Publishing

Set `project.version` in [pyproject.toml](../pyproject.toml) to the next `X.Y.Z` version. Run `uv lock` and include the lockfile update in the same commit. Use three nonnegative integers without leading zeroes or a prerelease suffix. Keep the version unchanged for commits that do not need a release. The first version is `0.1.0`.

The [check workflow](../.github/workflows/check.yml) publishes a normal GitHub release with generated notes after a push to `main` passes lint, quality, portable tests and all four [host checks](../host/README.md#check-without-deployment). It creates `vX.Y.Z` at the exact commit those jobs tested. It does not publish a package or deploy services. Native and live workstation tests remain separate.

The workflow token is read-only by default. Only the release job gets `contents: write`. Pull requests cannot run that job. Publication runs one job at a time per repository and does not cancel an active publisher. The publisher checks the event, branch, checked-out commit and version before contacting GitHub. It never prints CLI response bodies or credentials.

Tags are permanent version identities. The publisher never moves or deletes one. An existing normal release is skipped when its named tag exists as a direct commit reference. The tag determines the commit, even when release metadata names a branch. A missing tag, draft, prerelease, annotated tag or mismatched tag name stops publication for inspection.

If a run creates the tag but fails before publishing, rerun the failed job from that workflow run. It reuses the tag only at the same tested commit. A manual `check` workflow dispatch on `main` also runs every gate before publication. If `main` has advanced past an unpublished tag, recover the original run instead of moving the tag. A failed GitHub request stops the job. Inspect the Actions log, restore access or service availability, then retry. GitHub can refuse an older commit when its workflow files differ from the current default branch. Keep the tag fixed and choose a new version on current `main` if that prevents recovery.

The [release tests](../tests/integration/release) run the publisher against a local GitHub CLI stand-in. They cover the first release, unchanged versions, interrupted publication, conflicting tags, invalid versions, event restrictions and API failures without remote writes.
