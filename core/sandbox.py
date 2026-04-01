"""Path sandboxing — restrict file operations to the working directory."""

import os


def validate_path(path: str, working_dir: str | None) -> tuple[str, str | None]:
    """
    Resolve a path and verify it's within the working directory.
    Returns (resolved_path, error_message).
    If error_message is not None, the path is invalid.
    """
    if not working_dir:
        return path, None  # No sandbox if no working dir set

    # Resolve both to absolute paths
    resolved = os.path.realpath(os.path.join(working_dir, path))
    sandbox = os.path.realpath(working_dir)

    # Check the resolved path is within the sandbox
    if not resolved.startswith(sandbox + os.sep) and resolved != sandbox:
        return "", f"Error: Access denied — path '{path}' is outside the project directory"

    return resolved, None
