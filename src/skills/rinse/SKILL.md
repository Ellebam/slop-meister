---
description: "Rinse: run this on every draft you write for anyone but the operator, before you show or send it and again after each change. It covers commit messages, pull request and merge request text, ticket and review comments, Jira or Confluence updates, published artifacts and pages, mails and messages, before any push, and whenever asked whether a text is ready. It checks for traces of our workflow, cryptic wording, the writing rules and our voice. It changes nothing and gives the same findings for the same text, so it is safe to repeat."
---

# Rinse

Every reader other than the operator gets a short, plain text in our voice. Customers see our results, never our workflow, our agents or our machine.

## What it runs on

Every outward text in every plot. These are pull request and merge request titles and descriptions, commit messages, ticket and review comments, Jira and Confluence updates, published artifacts and pages, mails, and chat messages to people other than the operator. Chat answers to the operator are not outward text.

Run the checks on the finished draft, after you write it and again after every change. Reading this skill before you write is not a run.

## Read the rules first

Read these before you judge a text, and again when they change.

- The plot's rules for outputs in this session's instructions, its wording rules included.
- The vault guideline index `_system/guidelines/README.md` and every guideline it names for this kind of text. Use its writing rules and any configured surface rules for documents, tracker text, commits and reviews. A missing local convention grants no exception to the active session rules.
- The plot's vault context note `fields/<plot>/CONTEXT.md` and the notes it routes to on how we write for this project, such as `CUSTOMER.md`, its `conventions/` notes and earlier approved drafts.

## Read what leaves

- Text. The exact words to be posted or sent, titles included.
- Git. Every added line, new file name and commit message a push would publish, including the message about to be written. Read `git log -p --cc <base>..HEAD`, `git diff --cached`, `git diff` and the untracked files. `<base>` is the remote branch the push updates, or the remote default branch for a new branch.

## Checks

- Traces, where the plot says we do not fully own the project. Look for these kinds.
  - Workflow. Slopmeister, plot, skill and procedure names used as such, spine steps, notes files and their headings, reviewers and testers, `.worktrees/` and scratch paths.
  - Agents. Tool and model names, co-author and generated-with lines.
  - Machine. The home directory path, the user name, `/private/tmp`, `/var/folders/`, local ports and container names.
  - Other customers. Anything from another customer.

  Plan, frame, ship or merge in their product sense are not traces.
- Cryptic wording. Every identifier, abbreviation and ticket number is explained or linked for this reader. A bare ticket number is unexplained even where the platform links it, so say in a few words what it is. Sentences are short, plain and active. No internal label stands in for a plain word.
- Guidelines. The text meets the plot's rules for outputs and every guideline read above for this kind of text, including its format, required parts and patterns, language, tone, length and banned punctuation. The language follows the vault's rules for this reader, not the language of the notes, the code or earlier messages.
- Voice. The text reads like the project's earlier approved drafts. It has no robotic or machine-sounding phrasing and no word the operator would not use. It speaks for the team about the result and never about the writer's own session, such as what notes record, what this checkout holds or what the writer could not verify.

## Report

Rinse changes no file and gives the same findings for the same text. Name each finding by where it is and its kind, never a trace's value. Give the report in your reply. Say what you read, then each finding, or clean only after reading all of it against every rule above. Nothing leaves until every finding is fixed or the operator accepts it. Fix findings only in your own text and outside this check, ask before changing anything else, then rinse the changed text again.
