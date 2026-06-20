"""Minimal OpenTTD admin-port client.

The admin TCP port (default 3977) is how we observe and drive a headless OpenTTD server:
it relays console output (including GSLog from a GameScript) and runs rcon console commands.
This is our only observability channel here, since the Windows binary does not pipe stdout.

Protocol per docs/admin_network.md and src/network/core/tcp_admin.h (OpenTTD 15.3):
  frame      = uint16 size (LE, includes the 2 size bytes) + uint8 type + payload
  strings    = null-terminated UTF-8
  numbers    = little-endian
Requires the server to have an admin password set and allow_insecure_admin_login = true
(localhost use only; the insecure JOIN sends the password in the clear).

CLI:
  python tools/ottd_admin.py rcon "<command>"     run one console command, print output
  python tools/ottd_admin.py watch [seconds]      stream console output for N seconds
"""

from __future__ import annotations

import socket
import struct
import sys
import time
from typing import List, Tuple

# admin -> server packet types
P_ADMIN_JOIN = 0
P_ADMIN_QUIT = 1
P_ADMIN_UPDATE_FREQUENCY = 2
P_ADMIN_RCON = 5
# server -> admin packet types
P_SERVER_ERROR = 102
P_SERVER_PROTOCOL = 103
P_SERVER_WELCOME = 104
P_SERVER_RCON = 120
P_SERVER_CONSOLE = 121
P_SERVER_RCON_END = 125

ADMIN_UPDATE_CONSOLE = 6
FREQ_AUTOMATIC = 1 << 6   # AdminUpdateFrequency::Automatic as a bitset value


class AdminError(Exception):
    pass


class AdminClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 3977,
                 password: str = "ottdoom", timeout: float = 10.0):
        self.host, self.port, self.password = host, port, password
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self._buf = b""

    # -- framing --
    def _send(self, ptype: int, payload: bytes = b"") -> None:
        size = 3 + len(payload)
        self.sock.sendall(struct.pack("<H", size) + bytes([ptype]) + payload)

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise AdminError("server closed connection")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _recv_packet(self) -> Tuple[int, bytes]:
        size = struct.unpack("<H", self._recv_exact(2))[0]
        body = self._recv_exact(size - 2)
        return body[0], body[1:]

    @staticmethod
    def _str(payload: bytes, off: int) -> Tuple[str, int]:
        end = payload.index(b"\x00", off)
        return payload[off:end].decode("utf-8", "replace"), end + 1

    # -- session --
    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        payload = (self.password.encode() + b"\x00"
                   + b"openttdoom\x00" + b"1\x00")
        self._send(P_ADMIN_JOIN, payload)
        # expect PROTOCOL then WELCOME (ignore their contents)
        got_welcome = False
        t0 = time.time()
        while not got_welcome and time.time() - t0 < self.timeout:
            ptype, payload = self._recv_packet()
            if ptype == P_SERVER_ERROR:
                raise AdminError(f"server error on join (code {payload[:1].hex()}); "
                                 "check admin_password and allow_insecure_admin_login")
            if ptype == P_SERVER_WELCOME:
                got_welcome = True
        if not got_welcome:
            raise AdminError("did not receive WELCOME")

    def subscribe_console(self) -> None:
        self._send(P_ADMIN_UPDATE_FREQUENCY,
                   struct.pack("<HH", ADMIN_UPDATE_CONSOLE, FREQ_AUTOMATIC))

    def rcon(self, command: str, settle: float = 2.0) -> List[str]:
        """Run a console command. Returns the lines the server replied with."""
        self._send(P_ADMIN_RCON, command.encode() + b"\x00")
        lines: List[str] = []
        deadline = time.time() + max(settle, self.timeout)
        while time.time() < deadline:
            try:
                ptype, payload = self._recv_packet()
            except socket.timeout:
                break
            if ptype == P_SERVER_RCON:
                # uint16 colour, string message
                msg, _ = self._str(payload, 2)
                lines.append(msg)
            elif ptype == P_SERVER_RCON_END:
                break
            elif ptype == P_SERVER_CONSOLE:
                origin, off = self._str(payload, 0)
                msg, _ = self._str(payload, off)
                lines.append(f"[console:{origin}] {msg}")
            elif ptype == P_SERVER_ERROR:
                lines.append(f"[error code {payload[:1].hex()}]")
                break
        return lines

    def watch_console(self, seconds: float) -> List[str]:
        """Stream console output (incl. GSLog) for `seconds`. Returns the lines."""
        self.subscribe_console()
        lines: List[str] = []
        self.sock.settimeout(0.5)
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                ptype, payload = self._recv_packet()
            except socket.timeout:
                continue
            except AdminError:
                break
            if ptype == P_SERVER_CONSOLE:
                origin, off = self._str(payload, 0)
                msg, _ = self._str(payload, off)
                line = f"[{origin}] {msg}"
                lines.append(line)
                print(line, flush=True)
        return lines

    def close(self) -> None:
        try:
            if self.sock:
                self._send(P_ADMIN_QUIT)
                self.sock.close()
        except OSError:
            pass


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    c = AdminClient()
    try:
        c.connect()
    except (OSError, AdminError) as e:
        print(f"connect failed: {e}")
        return 1
    try:
        if cmd == "rcon":
            for line in c.rcon(" ".join(argv[1:])):
                print(line)
        elif cmd == "watch":
            secs = float(argv[1]) if len(argv) > 1 else 10.0
            c.watch_console(secs)
        else:
            print(f"unknown command {cmd}")
            return 2
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
