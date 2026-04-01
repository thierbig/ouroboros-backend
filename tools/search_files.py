"""Search file contents or find files by name pattern."""

import os
import re
import fnmatch
from pathlib import Path

SCHEMA = {
    "name": "search_files",
    "description": (
        "Search file contents or find files by name.\n\n"
        "Content search (target='content'): Regex search inside files with line numbers.\n"
        "File search (target='files'): Find files by glob pattern (e.g., '*.py')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern for content search, or glob pattern for file search",
            },
            "target": {
                "type": "string",
                "enum": ["content", "files"],
                "description": "'content' searches inside files, 'files' searches by filename",
                "default": "content",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: current directory)",
                "default": ".",
            },
            "file_glob": {
                "type": "string",
                "description": "Filter files by pattern in content mode (e.g., '*.py')",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default: 50)",
                "default": 50,
            },
        },
        "required": ["pattern"],
    },
}

# Track repeated searches
_search_history: dict[str, int] = {}


def _content_search(pattern: str, path: str, file_glob: str | None, limit: int) -> str:
    results = []
    search_path = Path(path)

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    for root, dirs, files in os.walk(search_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")]

        for filename in files:
            if file_glob and not fnmatch.fnmatch(filename, file_glob):
                continue

            filepath = os.path.join(root, filename)
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            rel_path = os.path.relpath(filepath, path)
                            results.append(f"{rel_path}:{line_num}: {line.rstrip()}")
                            if len(results) >= limit:
                                break
            except (PermissionError, OSError):
                continue

            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    if not results:
        return "No matches found."

    output = "\n".join(results)
    if len(results) >= limit:
        output += f"\n\n[Results limited to {limit}. Use a more specific pattern to narrow results.]"
    return output


def _file_search(pattern: str, path: str, limit: int) -> str:
    results = []
    search_path = Path(path)

    for root, dirs, files in os.walk(search_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")]

        for filename in files:
            if fnmatch.fnmatch(filename, pattern):
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, path)
                results.append(rel_path)
                if len(results) >= limit:
                    break
        if len(results) >= limit:
            break

    if not results:
        return "No files found."

    return "\n".join(sorted(results))


def handle(args: dict, working_dir: str | None = None) -> str:
    from core.sandbox import validate_path
    pattern = args["pattern"]
    target = args.get("target", "content")
    path = args.get("path", ".")
    if working_dir:
        path, err = validate_path(path, working_dir)
        if err:
            return err
    file_glob = args.get("file_glob")
    limit = args.get("limit", 50)

    search_key = f"{pattern}|{target}|{path}|{file_glob}"
    _search_history[search_key] = _search_history.get(search_key, 0) + 1
    count = _search_history[search_key]

    if count >= 4:
        return (
            f"BLOCKED: You have run this same search {count} times. "
            "The results have NOT changed. "
            "STOP re-searching and proceed with your task."
        )

    if target == "files":
        return _file_search(pattern, path, limit)
    else:
        return _content_search(pattern, path, file_glob, limit)


def register(reg):
    reg.register("search_files", SCHEMA, handle)
