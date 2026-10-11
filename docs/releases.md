# Releases

Set `project.version` in [pyproject.toml](../pyproject.toml) to the next `X.Y.Z` version. Run `uv lock` and include the lockfile update in the same commit. Use three nonnegative integers without leading zeroes or a prerelease suffix. Keep the version unchanged for commits that do not need a release. The first version is `0.1.0`.

The [check workflow](../.github/workflows/check.yml) publishes a normal GitHub release with generated notes after a push to `main` passes lint, quality, portable tests and all four [host checks](../host/README.md#check-without-deployment). It creates `vX.Y.Z` at the exact commit those jobs tested. It does not publish a package or deploy services. Native and live workstation tests remain separate.

The workflow token is read-only by default. Only the release job gets `contents: write`. Pull requests cannot run that job. Publication runs one job at a time per repository and does not cancel an active publisher. The publisher checks the event, branch, checked-out commit and version before contacting GitHub. It never prints CLI response bodies or credentials.

Tags are permanent version identities. The publisher never moves or deletes one. An existing normal release is skipped when its named tag exists as a direct commit reference. The tag determines the commit, even when release metadata names a branch. A missing tag, draft, prerelease, annotated tag or mismatched tag name stops publication for inspection.

If a run creates the tag but fails before publishing, rerun the failed job from that workflow run. It reuses the tag only at the same tested commit. A manual `check` workflow dispatch on `main` also runs every gate before publication. If `main` has advanced past an unpublished tag, recover the original run instead of moving the tag. A failed GitHub request stops the job. Inspect the Actions log, restore access or service availability, then retry. GitHub can refuse an older commit when its workflow files differ from the current default branch. Keep the tag fixed and choose a new version on current `main` if that prevents recovery.

The [release tests](../tests/integration/release) run the publisher against a local GitHub CLI stand-in. They cover the first release, unchanged versions, interrupted publication, conflicting tags, invalid versions, event restrictions and API failures without remote writes.
