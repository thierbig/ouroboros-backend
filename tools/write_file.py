"""Write content to a file, creating parent directories automatically."""

import os

SCHEMA = {
    "name": "write_file",
    "description": (
        "Write content to a file, completely replacing existing content. "
        "Creates parent directories automatically. "
        "OVERWRITES the entire file — use 'patch' for targeted edits."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write (created if it doesn't exist)",
            },
            "content": {
                "type": "string",
                "description": "Complete content to write to the file",
            },
        },
        "required": ["path", "content"],
    },
}


def handle(args: dict, working_dir: str | None = None) -> str:
    from core.sandbox import validate_path
    path = args["path"]
    path, err = validate_path(path, working_dir)
    if err:
        return err
    content = args["content"]

    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"\u2713 Wrote {len(content)} bytes to {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def register(reg):
    reg.register("write_file", SCHEMA, handle)
