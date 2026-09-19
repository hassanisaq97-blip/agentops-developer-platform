class PathSecurityError(Exception):
    """Raised when a requested path would escape the workspace sandbox."""


class CommandSecurityError(Exception):
    """Raised when a requested command is not on the allowlist or has invalid arguments."""
