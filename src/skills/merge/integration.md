# Verify the merged tree

Keep the saved merge variables from step 3. For the CI route, set `merge_workflow` to the project's configured gate that passed on the checked head. This is a workflow name or identifier, never a command to evaluate. Read-only inspection and waiting need no new merge order. The block is also the already-merged replay path and makes no merge, branch, status or workflow-dispatch write.

The merge must be MERGED and its commit must exist locally after fetching the base. An equal tree reuses the pull request run only when the merge's first parent is an ancestor of the checked head. Every other tree needs successful CI on its exact merge commit. The CI-less bootstrap route keeps its earlier explicit authority and local proof, and has no run to await.

```bash
(
    integration_refuse() { printf 'INTEGRATION UNPROVEN: %s\n' "$1" >&2; exit 1; }
    : "${merge_repository:?INTEGRATION UNPROVEN: set merge_repository}"
    : "${merge_number:?INTEGRATION UNPROVEN: set merge_number}"
    : "${merge_base:?INTEGRATION UNPROVEN: set merge_base}"
    : "${merge_head:?INTEGRATION UNPROVEN: set merge_head}"
    : "${merge_proof:?INTEGRATION UNPROVEN: set merge_proof}"
    case "$merge_proof" in
        ci) : "${merge_workflow:?INTEGRATION UNPROVEN: set merge_workflow}" ;;
        bootstrap) ;;
        *) integration_refuse 'proof route must be ci or bootstrap' ;;
    esac
    merge_snapshot=$(gh pr view "$merge_number" --repo "github.com/$merge_repository" \
        --json state,mergeCommit --jq '[.state, .mergeCommit.oid] | join(" ")') \
        || integration_refuse 'merged PR read failed'
    merge_commit=${merge_snapshot#MERGED }
    if [ "$merge_snapshot" = "$merge_commit" ] || \
        ! printf '%s\n' "$merge_commit" | LC_ALL=C grep -Eq '^[a-f0-9]{40}$'; then
        integration_refuse 'PR is not merged with a valid commit'
    fi
    git fetch --no-tags origin "$merge_base" || integration_refuse 'base fetch failed'
    merge_tree=$(git rev-parse --verify --end-of-options "$merge_commit^{tree}") \
        || integration_refuse 'merge commit is unavailable'
    merge_head_tree=$(git rev-parse --verify --end-of-options "$merge_head^{tree}") \
        || integration_refuse 'checked head is unavailable'
    merge_contains_base=false
    if git merge-base --is-ancestor "$merge_commit^1" "$merge_head"; then
        merge_contains_base=true
    fi
    printf 'Merged tree %s; checked tree %s; base in head %s\n' \
        "$merge_tree" "$merge_head_tree" "$merge_contains_base"
    if [ "$merge_proof" = bootstrap ]; then
        [ "$merge_tree" = "$merge_head_tree" ] && [ "$merge_contains_base" = true ] \
            || integration_refuse 'bootstrap merged tree differs from its local proof'
        printf 'Integration proven by the authorized bootstrap proof: %s\n' "$merge_commit"
        exit 0
    fi
    merge_expected=$merge_commit
    merge_filter=(--branch "$merge_base")
    if [ "$merge_tree" = "$merge_head_tree" ] && [ "$merge_contains_base" = true ]; then
        merge_expected=$merge_head
        merge_filter=(--event pull_request)
    fi
    for merge_attempt in 1 2; do
        merge_run=$(gh run list --repo "github.com/$merge_repository" \
            --workflow "$merge_workflow" --commit "$merge_expected" "${merge_filter[@]}" \
            --limit 1 --json databaseId,headSha \
            --jq 'if length == 1 then "\(.[0].databaseId) \(.[0].headSha)" else "" end') \
            || integration_refuse 'integration run lookup failed'
        [ -z "$merge_run" ] || break
        [ "$merge_attempt" -eq 2 ] || sleep 30 || integration_refuse 'registration wait failed'
    done
    [ -n "$merge_run" ] || integration_refuse 'no exact-commit integration run'
    merge_run_id=${merge_run%% *}
    [ "$merge_run" = "$merge_run_id $merge_expected" ] && \
        printf '%s\n' "$merge_run_id" | LC_ALL=C grep -Eq '^[1-9][0-9]*$' \
        || integration_refuse 'integration run names another commit or invalid identity'
    gh run watch "$merge_run_id" --repo "github.com/$merge_repository" --exit-status \
        || integration_refuse 'integration gate did not succeed'
    merge_result=$(gh run view "$merge_run_id" --repo "github.com/$merge_repository" \
        --json headSha,status,conclusion --jq '[.headSha, .status, .conclusion] | join(" ")') \
        || integration_refuse 'integration result read failed'
    [ "$merge_result" = "$merge_expected completed success" ] \
        || integration_refuse 'integration gate is not successful on the exact commit'
    printf 'Integration proven: merge %s, run %s on %s\n' \
        "$merge_commit" "$merge_run_id" "$merge_expected"
)
```

Record both tree hashes, the ancestor result and the proving run's URL. A missing run stays unproven after the bounded registration wait. A pending, failed, cancelled or skipped gate is not success. Do not substitute a later commit's green run or dispatch a release or deployment workflow. On failure preserve the issue, claim and worktree, report the exact blocked proof and stop dependent actions.
