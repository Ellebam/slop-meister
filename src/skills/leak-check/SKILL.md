---
description: "Leak check: before anything leaves for a customer, make sure it shows nothing of how we work. Invoke before any commit, push, pull request text, review comment, Jira or Confluence update, or message draft goes to a project we do not fully own, again after it changes, and whenever asked whether something is clean to send. Safe to repeat."
---

# Leak check

Customers see our results, never our workflow, our agents or our machine.

## Read what leaves

- Text. The exact words to be posted or sent, titles included.
- Git. Every added line, new file name and commit message a push would publish, including the message about to be written. Read `git log -p --cc <base>..HEAD`, `git diff --cached`, `git diff` and the untracked files. `<base>` is the remote branch the push updates, or the remote default branch for a new branch.

## Traces

- Workflow. Slopmeister, plot, skill and procedure names used as such, spine steps, notes files and their headings, reviewers and testers, `.worktrees/` and scratch paths.
- Agents. Tool and model names, co-author and generated-with lines.
- Machine. The home directory path, the user name, `/private/tmp`, `/var/folders/`, local ports and container names.
- Other customers. Anything from another customer.

Plan, frame, ship or merge in their product sense are not traces.

## Report

Name each trace by where it is and its kind, never its value. Say clean only after reading all of it, and say what you read before handing anything over. Nothing leaves until every trace is gone or the operator accepts it. Remove traces only from your own work and check again, and ask before changing anything else.
