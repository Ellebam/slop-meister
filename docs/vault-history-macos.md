# Vault history on macOS

[Vault history](vault-version-control.md) · [Scheduled history](vault-history-scheduled.md)

## Give the applet access

macOS file-access consent belongs to the applet. If the job cannot list the vault it logs `NO ACCESS` and stops, rather than reporting an empty tree as a successful run.

1. Run the [named history installs](vault-version-control.md#enable-history-before-editing) when installation is intended. Installing the changed launchd entry reloads that job.
2. If the applet is missing, the install builds it, `task home:install -- .vault-git/VaultCommit.app` builds it alone.
3. Allow the first-run consent dialog. If dismissed, add `VaultCommit.app` under System Settings → Privacy and Security → Full Disk Access.

Inspect the job without running it:

```bash
launchctl print "gui/$(id -u)/local.vault-commit"
```

To request an immediate scheduled commit:

```bash
launchctl kickstart "gui/$(id -u)/local.vault-commit"
```

The [installer](../slopmeister/workstation/install.py) leaves an existing applet untouched because rebuilding changes its identity and revokes its consent. A failed build is reported while the rest of installation continues. The manual build command is:

```bash
osacompile -o ~/.vault-git/VaultCommit.app \
  -e 'do shell script "/bin/bash " & quoted form of (POSIX path of (path to home folder)) & ".vault-git/bin/vault-commit.sh"'
```

