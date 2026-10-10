"""Inspect native process identity and its input channel on each supported system."""

import ctypes
import os
from pathlib import Path
import socket
import struct
import sys

PROCESS_BUFFER = 65536
BSD_INFO_SIZE = 136
PIPE_INFO_SIZE = 184
PIPE_HANDLE_OFFSET = 160
PIPE_PEER_OFFSET = 168
PIPE_DESCRIPTOR_TYPE = 6
SOCKET_INFO_SIZE = 792
SOCKET_HANDLE_OFFSET = 160
SOCKET_PEER_OFFSET = 264
SOCKET_KIND_OFFSET = 256
SOCKET_DESCRIPTOR_TYPE = 2
SOCKET_INFO_FLAVOR = 3
SOCKET_UNIX_KIND = 3
DESCRIPTOR_SIZE = 8
DESCRIPTOR_KIND_OFFSET = 4
KERN_PROCARGS2 = (1, 49)
NATIVE_ERROR = "NATIVE_APPROVAL_REQUIRED"
PEER_CREDENTIALS = struct.Struct("3i")


def process(pid: int) -> tuple[Path, list[str], int]:
    if sys.platform == "linux":
        root = Path(f"/proc/{pid}")
        executable = root.joinpath("exe").readlink()
        argv = [
            value.decode("utf-8")
            for value in root.joinpath("cmdline").read_bytes().split(b"\0")[:-1]
        ]
        parent = int(root.joinpath("stat").read_text().rsplit(")", 1)[1].split()[1])
        return executable, argv, parent
    if sys.platform != "darwin":
        raise ValueError(NATIVE_ERROR)
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    path = ctypes.create_string_buffer(4096)
    bsd = ctypes.create_string_buffer(BSD_INFO_SIZE)
    if not library.proc_pidpath(pid, path, len(path)) or not library.proc_pidinfo(
        pid, 3, 0, bsd, len(bsd)
    ):
        raise ValueError(NATIVE_ERROR)
    parent = ctypes.c_uint.from_buffer(bsd, 16).value
    raw = ctypes.create_string_buffer(PROCESS_BUFFER)
    length = ctypes.c_size_t(len(raw))
    mib = (ctypes.c_int * 3)(*KERN_PROCARGS2, pid)
    if ctypes.CDLL(None).sysctl(mib, 3, raw, ctypes.byref(length), None, 0):
        raise ValueError(NATIVE_ERROR)
    count = ctypes.c_int.from_buffer(raw).value
    values = raw.raw[4 : length.value].split(b"\0")
    start = next((index for index, value in enumerate(values[1:], 1) if value), len(values))
    argv = [value.decode("utf-8") for value in values[start : start + count]]
    return Path(path.value.decode("utf-8")), argv, parent


def owned_pipe(parent: int) -> bool:
    if sys.platform == "linux":
        return _linux_pipe(parent)
    if sys.platform == "darwin":
        return _mac_pipe(parent)
    return False


def _mac_pipe(parent: int) -> bool:
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    own = ctypes.create_string_buffer(PIPE_INFO_SIZE)
    descriptors = ctypes.create_string_buffer(PROCESS_BUFFER)
    if library.proc_pidfdinfo(os.getpid(), 0, 6, own, len(own)) != PIPE_INFO_SIZE:
        return False
    peer = ctypes.c_uint64.from_buffer(own, PIPE_PEER_OFFSET).value
    length = library.proc_pidinfo(parent, 1, 0, descriptors, len(descriptors))
    for offset in range(0, length, 8):
        fd = ctypes.c_int.from_buffer(descriptors, offset).value
        kind = ctypes.c_uint.from_buffer(descriptors, offset + 4).value
        if kind != PIPE_DESCRIPTOR_TYPE:
            continue
        other = ctypes.create_string_buffer(PIPE_INFO_SIZE)
        if library.proc_pidfdinfo(parent, fd, 6, other, len(other)) == PIPE_INFO_SIZE:
            handle = ctypes.c_uint64.from_buffer(other, PIPE_HANDLE_OFFSET).value
            if handle == peer:
                return True
    return False


def _linux_pipe(parent: int) -> bool:
    own = os.fstat(0)
    root = Path(f"/proc/{parent}")
    for descriptor in root.joinpath("fd").iterdir():
        try:
            info = descriptor.stat()
            raw = root.joinpath("fdinfo", descriptor.name).read_text()
            flags = int(raw.split("flags:", 1)[1].split()[0], 8)
        except OSError, IndexError, ValueError:
            continue
        if (info.st_dev, info.st_ino) == (
            own.st_dev,
            own.st_ino,
        ) and flags & os.O_ACCMODE != os.O_RDONLY:
            return True
    return False


def owned_socket(parent: int) -> bool:
    if sys.platform == "linux":
        with socket.socket(fileno=os.dup(0)) as channel:
            credentials = channel.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, PEER_CREDENTIALS.size
            )
            creator, _, _ = PEER_CREDENTIALS.unpack(credentials)
            return channel.family == socket.AF_UNIX and creator == parent
    if sys.platform == "darwin":
        return _mac_socket(parent)
    return False


def _mac_socket(parent: int) -> bool:
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    own = ctypes.create_string_buffer(SOCKET_INFO_SIZE)
    descriptors = ctypes.create_string_buffer(PROCESS_BUFFER)
    if library.proc_pidfdinfo(os.getpid(), 0, SOCKET_INFO_FLAVOR, own, len(own)) != len(own):
        return False
    peer = ctypes.c_uint64.from_buffer(own, SOCKET_PEER_OFFSET).value
    if not peer or ctypes.c_int.from_buffer(own, SOCKET_KIND_OFFSET).value != SOCKET_UNIX_KIND:
        return False
    length = library.proc_pidinfo(parent, 1, 0, descriptors, len(descriptors))
    for offset in range(0, length, DESCRIPTOR_SIZE):
        fd = ctypes.c_int.from_buffer(descriptors, offset).value
        kind = ctypes.c_uint.from_buffer(descriptors, offset + DESCRIPTOR_KIND_OFFSET).value
        if kind != SOCKET_DESCRIPTOR_TYPE:
            continue
        other = ctypes.create_string_buffer(SOCKET_INFO_SIZE)
        if library.proc_pidfdinfo(parent, fd, SOCKET_INFO_FLAVOR, other, len(other)) == len(other):
            handle = ctypes.c_uint64.from_buffer(other, SOCKET_HANDLE_OFFSET).value
            if handle == peer:
                return True
    return False
