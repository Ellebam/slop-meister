"""The older versions the Drive sync sets aside when both sides edited one file."""

from pathlib import Path
import re

# The suffix plots/home/drive/drive-sync.sh gives the older version, before the extension.
COPY = re.compile(r"\.sync-conflict-[^./]+(\.[^./]+)?$")
STEPS = """\
merge each conflict copy from the vault folder, <note> is its name without the suffix:
  1. base: a committed version of <note> from before the edits of both files. Find it with
     vaultgit log -p -- <note> and write it with vaultgit show <commit>:<note> > <base>.
     When unsure take an older one, a base that holds one side's edit reverts it silently.
     Without such a version keep both files and ask the operator.
  2. git merge-file <note> <base> <copy>, exit 0 is merged, a positive exit counts the
     overlapping edits it left marked in <note>.
  3. read <note> against both files, remove <copy> and <base>, then commit <note> by name,
     and <copy> too when vaultgit status shows its deletion."""


def _visible(path: Path, vault: Path) -> bool:
    return not any(part.startswith(".") for part in path.relative_to(vault).parts)


def copies(vault: Path, root: Path, recursive: bool = True) -> list[str]:
    """Vault-relative conflict copies under root, hidden folders left out like the notes."""
    return sorted(
        str(path.relative_to(vault))
        for path in (root.rglob if recursive else root.glob)("*")
        if COPY.search(path.name) and path.is_file() and _visible(path, vault)
    )
