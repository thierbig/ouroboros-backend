"""Targeted find-and-replace edits in files."""

SCHEMA = {
    "name": "patch",
    "description": (
        "Targeted find-and-replace edit in a file. "
        "Finds old_string and replaces it with new_string. "
        "old_string must be unique in the file — include enough surrounding "
        "context to ensure uniqueness. new_string can be empty to delete text."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit",
            },
            "old_string": {
                "type": "string",
                "description": "Text to find (must be unique in the file)",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text (empty string to delete)",
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
}


def handle(args: dict, working_dir: str | None = None) -> str:
    from core.sandbox import validate_path
    path = args["path"]
    path, err = validate_path(path, working_dir)
    if err:
        return err
    old_string = args["old_string"]
    new_string = args["new_string"]

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"

    count = content.count(old_string)

    if count == 0:
        return (
            f"Error: old_string not found in {path}.\n\n"
            "[Hint: Use read_file to verify the current content, "
            "or search_files to locate the text.]"
        )

    if count > 1:
        return (
            f"Error: old_string found {count} times in {path}. "
            "It must be unique — include more surrounding context to disambiguate."
        )

    new_content = content.replace(old_string, new_string, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return f"✓ Applied patch to {path}"


def register(reg):
    reg.register("patch", SCHEMA, handle)
