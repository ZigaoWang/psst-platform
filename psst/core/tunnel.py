"""SSH port forwards to services that listen only on the server (the database and the fetch service).

One `ssh -N -L` process per remote port, opened on first use and closed when the process exits. The host is
`PSST_SSH_HOST` (an entry in ~/.ssh/config).
"""

from __future__ import annotations

import atexit
import socket
import subprocess
import time

from . import config

_forwards: dict[int, tuple[subprocess.Popen[bytes], int]] = {}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def local_port(remote_port: int) -> int:
    """A local port forwarded to `remote_port` on the server's loopback interface."""
    existing = _forwards.get(remote_port)
    if existing and existing[0].poll() is None:
        return existing[1]
    host = config.require("PSST_SSH_HOST")
    port = _free_port()
    process = subprocess.Popen(
        ["ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
         "-L", f"127.0.0.1:{port}:127.0.0.1:{remote_port}", host],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            error = process.stderr.read().decode().strip() if process.stderr else ""
            raise ConnectionError(f"SSH forward to {host} failed: {error}")
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                _forwards[remote_port] = (process, port)
                return port
        time.sleep(0.2)
    process.terminate()
    raise ConnectionError(f"SSH forward to {host} did not open within 20 seconds")


@atexit.register
def _close() -> None:
    for process, _ in _forwards.values():
        if process.poll() is None:
            process.terminate()
