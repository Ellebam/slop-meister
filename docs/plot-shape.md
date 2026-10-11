# Compose a plot

A plot combines shared rules with a project's own answers. The renderer turns those sources into the instructions each tool loads. What a launched session then receives is in [the launcher](launcher.md).

[Overview](../README.md) · [All documentation](README.md) · [Context and ownership](context-layer.md)

## Contents

- [Sources](#sources)
- [Declaration](#declaration)
- [The rendered shape](#the-rendered-shape)
- [Plot procedure trees](#plot-procedure-trees)
- [Procedure fill-in points](#procedure-fill-in-points)
- [What fails the render](#what-fails-the-render)

## Sources

Each plot lives under [plots/](../plots/). [code](../plots/code/plot.md) and [freeform](../plots/freeform/plot.md) are bases. [slopmeister](../plots/slopmeister/) composes directly on code. [inject](../plots/inject/) is a middle plot that other plots compose on.

| File or field | Rule |
|---|---|
| [plot.md](../plots/code/plot.md) | A base document. It cannot share a directory with plot.toml. |
| [plot.toml](../plots/slopmeister/plot.toml) | Makes a directory a composing plot. Requires `[plot] base`. |
| `base` | The base or middle plot this one composes on. A plot without a repository uses freeform, and a freeform plot may still use a repository worktree. |
| `open-points` | On a middle plot only, the markers it leaves open for the plots composing on it. |
| `<point>.md` | Fills the matching marker. An empty file explicitly opts out. |
| `skills/` | Optional plot-owned procedures, see [below](#plot-procedure-trees). |

A base declares each insertion point on its own line, `{{FILL:project}}` for example, and [project.md](../plots/slopmeister/project.md) in the composing plot fills it. Every marker needs a fragment and every fragment needs a marker. Point names use lowercase letters, digits and hyphens. Apart from `skills/`, a plot directory holds only plot.toml and fragments, and hidden entries are ignored.

A middle plot keeps exactly the markers its `open-points` names and has no render of its own. It composes on a base document, so at most one middle plot sits between a base and a launchable plot. The [example application](../plots/example-app/plot.toml) demonstrates direct composition on code with project fragments and a plot-owned skill.

## Declaration

Each composing plot has exactly one plot.toml. A `[target]` table makes it launchable. The shipped inventory has nine directories: `code`, `example-app`, `example-client`, `example-notes`, `freeform`, `home`, `inject`, `slopmeister` and `vault`. The five directories `code`, `freeform`, `home`, `inject` and `vault` are non-launchable. `task plot -- --list` includes all plot directories. A non-launchable directory has `template` in its second column and `-` in the remaining columns. The table name is only technical, it names no second concept beside the plot.

```toml
[plot]
base = "code"

[target]
tasks = "github"

[target.repository]
commit = "allow"
shipping = "allow"

[slots]
none = true
```

| Field | Values and meaning |
|---|---|
| `tasks` | `github`, `vault` or `manual`, which kickoff fetcher the launcher allows. |
| `repository` | Omit it, and `slots`, for a plot without a repository. |
| `repository.commit` | Required. `allow` or `deny`, see [Git approval](launcher.md#git-in-a-prepared-worktree). |
| `repository.shipping` | `allow` or `deny`, omitted means deny. With both `allow`, the fixed ship helper pushes the task branch and updates its PR without asking. |
| `repository.default` | Optional absolute or `~/` checkout path, used when the launch names no repository. |
| `service_actions` | Optional fixed read and write actions, see [service actions](service-actions.md). |
| `bloom` | `local` or `tailnet`, omitted means local. Tailnet permits publication of this plot's work through [Grove](agent-hosts.md#grove). The launcher saves the choice in the owning worktree, independent of Git permissions. |
| `slots` | Required with a repository, `none = true` or resources per [slots](slots.md#the-definition). |
| `[plot] seed` | `true` records that outside configuration was reviewed into Slopmeister. It changes nothing at runtime. |

The [shared validator](../slopmeister/plots/declaration.py) checks the whole tree before answering any lookup. Unknown fields, wrong types, contradictions, invalid names and unsafe paths fail with the file, key and reason, and nothing is trimmed or coerced. `task plot -- <name>` reads one plot, with `--commit`, `--shipping`, `--tasks` or `--slots` for one field and `--list` for the whole source directory inventory as TSV. Template rows cannot be used to launch a session. Tests point `PLOT_DECLARATIONS` at another declaration directory.

## The rendered shape

The base owns the single H1, the section headings and their order. Fragments add content only at declared points.

- A fragment cannot add an H1 outside a code fence. Subsections, and H2 sections at a tail point, are allowed.
- Headings use ATX syntax. Backtick and tilde fences count as code.
- Fragments are inserted once, top to bottom, with trailing whitespace removed. Nested markers fail except at a middle plot's open points.
- `{{TOOL}}` is substituted after composition. [dist/](../dist/) receives one plot file per tool and one row per plot in its [manifest](../dist/manifest.tsv).

A shared procedure under [src/skills/](../src/skills/) can carry tool blocks, each opened by a `{{TOOL:claude}}` or `{{TOOL:codex}}` line and closed by a `{{/TOOL}}` line. Everything outside the blocks is shared. Blocks cannot nest, appear in frontmatter or appear in plot sources, and code fences do not exempt them from validation.

## Plot procedure trees

Every procedure under [src/skills/](../src/skills/) reaches every session. A plot adds to that set with `skills/<name>/` folders in its own directory, and the folders are the whole declaration, so a plot cannot lose a shared procedure by forgetting to name it.

| Folder contents | Meaning | Constraint |
|---|---|---|
| Its own `SKILL.md` | The plot's own procedure. A shared name is shadowed for this plot only. | `skill.meta.yaml` is optional and carries Codex interface keys only. |
| No `SKILL.md` | A patch that adds this folder's files to the shared procedure of that name. | The shared procedure must exist, and rendered text must reference every added file. |

| Tool difference | Handling |
|---|---|
| A plot needs more Claude command permissions | Its `claude.frontmatter.yaml` supports only a non-empty `allowed-tools`, applied to the Claude render. |
| A procedure has Claude-only frontmatter such as `effort` | Claude keeps it, Codex keeps only `name` and `description`. |
| A plot's procedure shows Task or Docker format tokens | Exact dot-name tokens such as `{{.Names}}` stay literal. |

Plot procedures render under `dist/<tool>/targets/<plot>/skills/`, with manifest kind `target-skill`. A symlink anywhere in the tree fails the render. Delivery only adds, so withholding a shared procedure from one plot is not expressible.

## Procedure fill-in points

[local-qa](../src/skills/local-qa/SKILL.md) and [test-guide](../src/skills/test-guide/SKILL.md) describe generic work but need a project's commands. They name headings in the agreement's `Proving it here` section, and each composing plot fills them.

| Point | Project supplies |
|---|---|
| `local-qa-drive` | How to exercise the change through its real interface. |
| `local-qa-gates` | Checks that run only on this machine. |
| `test-guide-access` | How a tester reaches the change. |

The base owns each heading and a generic lead sentence, and an empty fragment leaves that generic rule alone. These procedures carry no double-brace tokens and render identically for both tools.

> [!IMPORTANT]
> Heading text binds procedure and agreement, so rename both together. A new point needs a fragment in every plot on that base. The [renderer tests](../tests/integration/render/test_procedures.py) catch either side moving alone.

## What fails the render

The [renderer](../slopmeister/render/build.py) reads only repository sources and is deterministic, two renders are byte-identical. `bin/slopmeister render --check` compares against the committed [dist/](../dist/), and every failure names the file to fix.

| Area | Rejected input |
|---|---|
| Sources | Missing base, a directory with both plot.md and plot.toml, symlinked source, unexpected plot file, CR line endings. |
| Points | Missing or unused fragment, duplicate or invalid point name, unfilled marker. |
| Middle plots | Invalid open points, a different surviving marker set, or composition onto a plot that leaves no points open. |
| Procedure trees | A patch on a missing shared procedure, an added file nothing references, unsupported Claude metadata, a symlink. |
| Tokens | An unsupported double-brace token, a malformed or nested tool block, a marker in a forbidden place. |

The [global source](../plots/home/global.md) is installed separately and composes with no plot. [Vault tooling](../plots/vault/) and [test data](../tests/data/) are not plots.
