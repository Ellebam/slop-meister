"""Delete a directory tree that holds read-only entries."""

from collections.abc import Callable
import os
from pathlib import Path
import shutil
import stat


def remove_tree(root: Path) -> None:
    """Delete root. Only directories inside it become writable, and no symlink is followed."""

    def retry(function: Callable[..., object], path: str, error: BaseException) -> None:
        if not isinstance(error, PermissionError) or function not in (os.unlink, os.rmdir):
            raise error
        parent = Path(path).parent
        if not parent.is_relative_to(root):
            raise error
        mode = parent.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise error
        # Removing a read-only cache file requires write permission on its directory.
        parent.chmod(mode | stat.S_IWUSR | stat.S_IXUSR, follow_symlinks=False)
        function(path)

    shutil.rmtree(root, onexc=retry)
