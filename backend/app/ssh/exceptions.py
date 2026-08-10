class SshError(Exception):
    """Base class for all SSH-related failures surfaced to the API/UI."""


class SshConnectError(SshError):
    """Could not establish the TCP/SSH connection (unreachable, refused, timeout)."""


class SshAuthError(SshError):
    """Connected, but authentication failed (bad password/key)."""


class SshHostKeyError(SshError):
    """The server's host key does not match the previously pinned one."""


class SshCommandError(SshError):
    """A remote command (tail, sftp listing, ...) failed."""
