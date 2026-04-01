"""Read file contents with line numbers and pagination."""

SCHEMA = {
    "name": "read_file",
    "description": (
        "Read a text file with line numbers and pagination. "
        "Output format: 'LINE_NUM|CONTENT'. "
        "Use offset and limit for large files."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed, default: 1)",
                "default": 1,
                "minimum": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read (default: 500, max: 2000)",
                "default": 500,
                "maximum": 2000,
            },
        },
        "required": ["path"],
    },
}


SENSITIVE_PATTERNS = {".env", ".secret", "credentials", "private_key", ".pem", ".key"}


def handle(args: dict, working_dir: str | None = None) -> str:
    import os
    from core.sandbox import validate_path
    path = args["path"]
    path, err = validate_path(path, working_dir)
    if err:
        return err
    if any(pat in os.path.basename(path).lower() for pat in SENSITIVE_PATTERNS):
        return "Error: Access denied — cannot read sensitive files"
    offset = args.get("offset", 1)
    limit = args.get("limit", 500)

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"

    if not lines:
        return "(empty file)"

    start = max(0, offset - 1)
    end = start + limit
    selected = lines[start:end]

    numbered = []
    for i, line in enumerate(selected, start=start + 1):
        numbered.append(f"{i}|{line.rstrip()}")

    result = "\n".join(numbered)

    total_lines = len(lines)
    if end < total_lines:
        result += f"\n\n[Showing lines {start + 1}-{min(end, total_lines)} of {total_lines}. Use offset={end + 1} to see more.]"

    return result


def register(reg):
    reg.register("read_file", SCHEMA, handle)
