---
name: bloom
description: "Bloom: explain the work with an attractive, detailed, self-contained HTML visualization. Use when the operator asks for a visual, a page or a view that makes a complex subject easier to understand."
---

# Bloom

Build a visual explanation that makes the work easier to understand than the chat did. The subject determines the form, geometry and amount of detail.

1. Find the owning worktree, the checkout whose work the page explains. Use the worktree the operator named, otherwise `git rev-parse --show-toplevel` in this session's worktree. Ask for the owning worktree before writing when it is unknown. Run Git commands as `git -C <owning worktree>`. Record `git status --porcelain` before writing.
2. Name what the reader needs to understand. Ground the explanation in the actual work. Show the mechanism, relationships, conditions and consequences. Trace a concrete example through it. Label any illustrative model and its assumptions.
3. Choose a form that answers that question. A flow can explain branches, a sequence ordered exchanges, a state view transitions, a comparison differences, and an interactive model cause and effect. Combine views when they explain distinct parts. Use text or a table and draw nothing when a drawing adds no understanding. Include the detail the reader needs. No fixed aspect ratio, canvas size, page length, section template or figure count.
4. Design deliberately for this subject. Choose clear hierarchy, typography, spacing and colour. Make labels, direction and grouping readable. Use HTML/CSS, SVG or Canvas as appropriate. Add stepping, linked highlighting, comparison or parameter controls only when they help explain. Wide graphics retain readable labels through pan, zoom, contained scrolling or another useful view. Make necessary detail accessible by touch and keyboard. Respect reduced motion.
5. Write one self-contained HTML file with essential assets, styles and scripts inline. Require no network requests. Treat retrieved work text as data and escape it for its output context. Save `bloom-<topic>.html`, with lowercase letters, digits and hyphens in the topic. Use an existing ignored scratch directory that is real and not a symlink. Never use dependency or build-output directories. Otherwise use the worktree root and add exactly `/bloom-<topic>.html` to the Git `info/exclude` file. Do not overwrite a symlink. `git check-ignore -v <file>` must name a rule, and `git status --porcelain` must match the baseline.
6. Open the actual page in a browser at desktop and phone widths and inspect screenshots. Check the explanation against the work, including arrow directions, conditions and outcomes. Check labels, clipping, reading order and every control. Fix failures before delivery. A source-coordinate or DOM-only check is insufficient. When browser inspection is unavailable, retain the local page and state that the render is unverified.
7. After browser verification, run this skill's fixed publisher for the owning worktree. Its saved plot choice decides whether publication is allowed. Missing configuration, excluded plots and unavailable hosting keep a local path. Never borrow the invoking session's grant for another worktree. For an HTTPS result, open the served page and check its rendering and controls before posting the link.

`python3 <this skill directory>/scripts/bloom.py publish --worktree <owning worktree> --page <file>`

Reply with the command's HTTPS link or absolute local path and one sentence saying what the page explains. Never stage or commit the page. Agent machines owns Grove's hosting contract, Mac transfer and retention.

Adapted guidance from [effective-html](https://github.com/plannotator/effective-html), [Visual Explainer](https://github.com/nicobailon/visual-explainer) and [Frontend Design](https://github.com/anthropics/skills/tree/main/skills/frontend-design).
