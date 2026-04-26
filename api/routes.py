"""REST API routes for admin, config, and file viewer."""

import os
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body, UploadFile, File, Form
from bson import ObjectId
from db.models import list_sessions, list_sessions_for_project, get_session, get_chunks_for_session, get_latest_session_for_project, hide_session

router = APIRouter()

# Directory containing demo/user projects the agent can work on
PROJECTS_DIR = os.environ.get("PROJECTS_DIR", str(Path(__file__).parent.parent / "demos"))


_NETLIFY_URL_RE = re.compile(r'https://[a-zA-Z0-9-]+\.netlify\.app')


async def _detect_deploy_url_from_sessions(working_dir: str) -> str | None:
    """Scan recent sessions for a netlify.app URL — take the most recent mention."""
    try:
        from db.connection import get_database
        db = await get_database()
        sessions = await db.sessions.find(
            {"working_dir": working_dir, "hidden": {"$ne": True}},
            sort=[("created_at", -1)],
        ).to_list(20)
        for s in sessions:
            for msg in reversed(s.get("messages", [])):
                content = msg.get("content", "") or ""
                match = _NETLIFY_URL_RE.search(content)
                if match:
                    return match.group(0)
    except Exception:
        pass
    return None


def _detect_deploy_url_from_files(project_dir: Path) -> str | None:
    """Fallback: check lessons.md for a deploy URL."""
    lessons = project_dir / "tasks" / "lessons.md"
    if lessons.exists():
        try:
            text = lessons.read_text(encoding="utf-8", errors="replace")
            match = _NETLIFY_URL_RE.search(text)
            if match:
                return match.group(0)
        except Exception:
            pass
    return None


async def _detect_deploy_url(project_dir: Path) -> str | None:
    """Resolve the actual deployed URL — prefer recent session messages over files."""
    working_dir = str(project_dir.resolve())
    url = await _detect_deploy_url_from_sessions(working_dir)
    if url:
        return url
    return _detect_deploy_url_from_files(project_dir)


async def _find_deploy_session(working_dir: str, deploy_url: str) -> str | None:
    """Find the session that deployed this URL."""
    from db.connection import get_database
    db = await get_database()
    # Search sessions for this project that mention the deploy URL
    sessions = await db.sessions.find(
        {"working_dir": working_dir, "hidden": {"$ne": True}},
        sort=[("created_at", -1)],
    ).to_list(20)
    for s in sessions:
        for msg in s.get("messages", []):
            content = msg.get("content", "") or ""
            if deploy_url in content or "netlify.app" in content:
                return str(s["_id"])
    return None


def serialize_doc(doc: dict) -> dict:
    if doc is None:
        return None
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    if "session_id" in doc:
        doc["session_id"] = str(doc["session_id"])
    return doc


AVAILABLE_MODELS = {
    "anthropic": [
        {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
        {"id": "claude-opus-4-20250514", "name": "Claude Opus 4"},
        {"id": "claude-haiku-3-5-20241022", "name": "Claude Haiku 3.5"},
    ],
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
    ],
}


@router.get("/models")
async def get_models(provider: str = "anthropic"):
    if provider not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    return {"provider": provider, "models": AVAILABLE_MODELS[provider]}


@router.get("/projects")
async def list_projects():
    """List available projects the agent can work on."""
    projects_path = Path(PROJECTS_DIR)
    if not projects_path.exists():
        return []
    projects = []
    for entry in sorted(projects_path.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            # Check if project has actual code (more than just CLAUDE.md + tasks/)
            scaffold_only = {"CLAUDE.md", "tasks"}
            actual_files = {f.name for f in entry.iterdir() if not f.name.startswith(".")}
            has_code = bool(actual_files - scaffold_only)

            deploy_url = await _detect_deploy_url(entry)
            deploy_session_id = None
            if deploy_url:
                deploy_session_id = await _find_deploy_session(str(entry.resolve()), deploy_url)

            # Detect project type from CLAUDE.md
            project_type = "price-game"
            claude_md = entry / "CLAUDE.md"
            if claude_md.exists():
                try:
                    content = claude_md.read_text(encoding="utf-8", errors="replace")
                    if "Entropy" in content or "IEntropyConsumer" in content:
                        project_type = "entropy-game"
                    elif "Custom Game" in content:
                        project_type = "custom-game"
                except Exception:
                    pass

            projects.append({
                "id": entry.name,
                "name": entry.name.replace("-", " ").title(),
                "path": str(entry.resolve()),
                "has_claude_md": (entry / "CLAUDE.md").exists(),
                "has_lessons_md": (entry / "tasks" / "lessons.md").exists(),
                "has_code": has_code,
                "deploy_url": deploy_url,
                "deploy_session_id": deploy_session_id,
                "project_type": project_type,
            })
    return projects


@router.post("/projects")
async def create_project(body: dict = Body(...)):
    """Create a new project directory with optional CLAUDE.md."""
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")

    # Slugify: "My Cool App" → "my-cool-app"
    project_id = name.lower().replace(" ", "-")
    project_id = "".join(c for c in project_id if c.isalnum() or c == "-")

    project_path = Path(PROJECTS_DIR) / project_id
    if project_path.exists():
        raise HTTPException(status_code=409, detail=f"Project '{project_id}' already exists")

    project_path.mkdir(parents=True)

    # Template-specific project context and stack constraints
    template_id = body.get("template", "custom-game")

    STACK_ENTROPY_GAME = """## Stack (Entropy Game — Solidity + Foundry + Pyth Entropy)

### Smart Contract (Foundry)
- Use Foundry (forge) for Solidity development
- Install Pyth SDK: `forge install pythnet/pyth-crosschain`
- Your contract must implement `IEntropyConsumer` for verifiable randomness
- Pyth Entropy on Base Sepolia: `0x4821932D0CDd71225A6d914706A621e0389D7061`
- Deploy with the `pyth_deploy` tool (compiles + deploys to Base Sepolia)

### Frontend (Vite + React)
- Scaffold: `bun create vite . --template react`
- Use ethers.js or viem for contract interaction
- **IMPORTANT: Use the Pyth Hermes REST API for ALL price data in the app.**
  See "Pyth Hermes API Integration" section below for how to fetch prices from JavaScript.
- Deploy frontend to Netlify

### Package Manager
Always use `bun` (not npm/yarn).
"""

    STACK_PRICE_GAME = """## Stack (Price Game — Vite Frontend + Pyth Hermes API)

### Frontend (Vite + React)
- Scaffold: `bun create vite . --template react`
- **IMPORTANT: Use the Pyth Hermes REST API for ALL price data in the app.**
  See "Pyth Hermes API Integration" section below for how to fetch prices from JavaScript.
- Use `pyth_price`, `pyth_search`, `pyth_candles` tools to explore data while building
- Deploy to Netlify

### Package Manager
Always use `bun` (not npm/yarn).
"""

    STACK_CUSTOM_GAME = """## Stack (Custom Game)
- Ask the user which Pyth Network features they want to use:
  - **Price Feeds**: Real-time asset prices via Pyth Hermes REST API
  - **Entropy**: Verifiable on-chain randomness (requires Solidity + Foundry)
  - **Both**: Full-featured game with prices and randomness
- Use `pyth_price`, `pyth_search`, `pyth_candles`, and `pyth_history` tools to explore available data
- Use `pyth_deploy` tool to deploy Solidity contracts to Base Sepolia
- **IMPORTANT: Use the Pyth Hermes REST API for ALL price data in deployed apps.**
  See "Pyth Hermes API Integration" section below.
- For frontends, use Vite + React and deploy to Netlify
- Use `bun` as package manager
"""

    template_stacks = {
        "entropy-game": STACK_ENTROPY_GAME,
        "price-game": STACK_PRICE_GAME,
        "custom-game": STACK_CUSTOM_GAME,
    }
    stack_section = template_stacks.get(template_id, STACK_CUSTOM_GAME)

    template_descriptions = {
        "entropy-game": "On-chain game using Pyth Entropy for verifiable randomness on Base Sepolia.",
        "price-game": "Frontend game powered by real-time Pyth price feeds via Hermes REST API.",
        "custom-game": "Custom Pyth Network game — ask the user which features to use.",
    }
    project_desc = template_descriptions.get(template_id, template_descriptions["custom-game"])

    # Create default CLAUDE.md with practical agent instructions
    default_claude = f"""# {name}

## Project Context
{project_desc}

{stack_section}

## Pyth Hermes API Integration (for deployed apps)

**ALL price data in deployed apps MUST use the Pyth Hermes REST API** at `https://hermes.pyth.network`.
The Hermes API supports CORS, requires no API key, and works directly in browsers.

### How to fetch prices from JavaScript:

```javascript
// Common Pyth feed IDs
const FEED_IDS = {{
  'BTC/USD': 'e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43',
  'ETH/USD': 'ff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace',
  'SOL/USD': 'ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d',
}};

// Fetch latest price
async function getPythPrice(feedId) {{
  const res = await fetch(`https://hermes.pyth.network/v2/updates/price/latest?ids[]=${{feedId}}`);
  const data = await res.json();
  const price = data.parsed[0].price;
  // price.price is a string, price.expo is negative exponent
  // Actual price = parseInt(price.price) * 10^price.expo
  return parseInt(price.price) * Math.pow(10, price.expo);
}}

// Streaming prices (SSE) for real-time updates
const evtSource = new EventSource(
  `https://hermes.pyth.network/v2/updates/price/stream?ids[]=${{feedId}}`
);
evtSource.onmessage = (e) => {{
  const data = JSON.parse(e.data);
  const price = data.parsed[0].price;
  const value = parseInt(price.price) * Math.pow(10, price.expo);
  console.log('Live price:', value);
}};
```

### Hermes API endpoints (no API key needed):
- **Latest price**: `GET /v2/updates/price/latest?ids[]=<feed_id>`
- **Streaming (SSE)**: `GET /v2/updates/price/stream?ids[]=<feed_id>`
- **Search feeds**: `GET /v2/price_feeds?query=<symbol>`

### Common feed IDs:
- BTC/USD: `e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43`
- ETH/USD: `ff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace`
- SOL/USD: `ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d`
- Use `pyth_search` tool or `/v2/price_feeds?query=` to discover more

## Rules

### 1. Talk First, Code Second
- Ask the user questions one at a time to understand what they want
- Do NOT search files or read task files as your first action
- Once requirements are clear, then start building

### 2. Auto-Deploy
- After building a web project, ALWAYS deploy it to Netlify automatically — do NOT ask the user
- Build first, then deploy immediately. The user wants to see it live.

### 3. Verify Before Done
- Never say you're done without proving it works
- Run the code, check for errors, test the output
- If something breaks, fix it yourself — don't ask the user how

### 4. Keep It Simple
- Make every change as simple as possible
- No over-engineering — build what was asked for
- Find root causes, no temporary fixes

### 5. Autonomous Execution
- When given a task: just do it. Don't ask for hand-holding
- Read the relevant code, make the changes, verify they work
- Only ask the user when there's a genuine ambiguity or choice to make

### 6. Quality Standards
- Read existing code before editing
- Use `patch` for edits, `write_file` for new files
- Check terminal exit codes — fix errors before moving on
"""
    claude_content = body.get("claude_md", default_claude)
    (project_path / "CLAUDE.md").write_text(claude_content, encoding="utf-8")

    # Create tasks directory with empty lessons.md
    tasks_dir = project_path / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    (tasks_dir / "lessons.md").write_text("# Lessons Learned\n\n", encoding="utf-8")
    (tasks_dir / "todo.md").write_text(f"# {name} — Tasks\n\n", encoding="utf-8")

    return {
        "id": project_id,
        "name": name,
        "path": str(project_path.resolve()),
    }


@router.post("/projects/upload")
async def upload_file(
    file: UploadFile = File(...),
    project_path: str = Form(...),
):
    """Upload a file to a project directory."""
    project_dir = Path(project_path)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    # Sanitize filename
    filename = file.filename or "upload"
    filename = filename.replace("\\", "/").split("/")[-1]  # strip path components

    dest = project_dir / filename
    content = await file.read()
    dest.write_bytes(content)

    return {"filename": filename, "path": str(dest), "size": len(content)}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project directory."""
    import shutil
    project_path = Path(PROJECTS_DIR) / project_id
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    def _force_remove_readonly(func, path, exc):
        """Handle Windows locked/read-only files (e.g. .git pack files)."""
        import stat
        os.chmod(path, stat.S_IWRITE)
        func(path)

    shutil.rmtree(project_path, onexc=_force_remove_readonly)
    return {"status": "ok"}


@router.get("/projects/{project_id}/config")
async def get_project_config(project_id: str):
    """Get CLAUDE.md and lessons.md for a project."""
    project_path = Path(PROJECTS_DIR) / project_id
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    claude_md = ""
    lessons_md = ""
    claude_path = project_path / "CLAUDE.md"
    lessons_path = project_path / "tasks" / "lessons.md"

    if claude_path.exists():
        claude_md = claude_path.read_text(encoding="utf-8", errors="replace")
    if lessons_path.exists():
        lessons_md = lessons_path.read_text(encoding="utf-8", errors="replace")

    return {
        "project_id": project_id,
        "claude_md": claude_md,
        "lessons_md": lessons_md,
    }


@router.put("/projects/{project_id}/claude-md")
async def update_claude_md(project_id: str, content: str = Body(..., media_type="text/plain")):
    """Update CLAUDE.md for a project."""
    project_path = Path(PROJECTS_DIR) / project_id
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    (project_path / "CLAUDE.md").write_text(content, encoding="utf-8")
    return {"status": "ok"}


@router.put("/projects/{project_id}/lessons-md")
async def update_lessons_md(project_id: str, content: str = Body(..., media_type="text/plain")):
    """Update tasks/lessons.md for a project."""
    project_path = Path(PROJECTS_DIR) / project_id
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    tasks_dir = project_path / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    (tasks_dir / "lessons.md").write_text(content, encoding="utf-8")
    return {"status": "ok"}


@router.get("/sessions")
async def get_project_sessions(working_dir: str):
    """List all sessions for a project (without full message bodies)."""
    sessions = await list_sessions_for_project(working_dir)
    result = []
    for s in sessions:
        # Extract a preview from the first user message
        preview = ""
        msg_count = 0
        if s.get("messages"):
            msg_count = len([m for m in s["messages"] if m.get("role") == "user"])
            for m in s["messages"]:
                if m.get("role") == "user" and m.get("content"):
                    preview = m["content"][:120]
                    break
        result.append({
            "_id": str(s["_id"]),
            "created_at": s.get("created_at"),
            "model": s.get("model"),
            "total_tokens": s.get("total_tokens", 0),
            "message_count": msg_count,
            "preview": preview,
        })
    return result


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Soft-delete a session (hide from users, keep stats)."""
    await hide_session(session_id)
    return {"status": "ok"}


@router.get("/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """Lightweight status check for a session."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": session.get("status", "unknown"), "total_tokens": session.get("total_tokens", 0)}


@router.get("/sessions/latest")
async def get_latest_session(working_dir: str):
    """Get the most recent session for a project, including chat messages."""
    session = await get_latest_session_for_project(working_dir)
    if not session:
        return None
    return serialize_doc(session)


SENSITIVE_PATTERNS = {".env", ".secret", "credentials", "private_key", ".pem", ".key"}


def _is_sensitive(path: str) -> bool:
    """Block access to files that may contain secrets."""
    name = Path(path).name.lower()
    return any(pat in name for pat in SENSITIVE_PATTERNS)


@router.get("/files/{path:path}")
async def read_file(path: str):
    # FastAPI strips the leading '/' from absolute paths — restore it
    if not Path(path).is_absolute() and path.startswith("app/"):
        path = "/" + path
    if _is_sensitive(path):
        raise HTTPException(status_code=403, detail="Access denied: sensitive file")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": path, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")


@router.get("/files-raw/{path:path}")
async def read_file_raw(path: str):
    """Serve a file as raw bytes (for images)."""
    if not Path(path).is_absolute() and path.startswith("app/"):
        path = "/" + path
    if _is_sensitive(path):
        raise HTTPException(status_code=403, detail="Access denied: sensitive file")
    from fastapi.responses import FileResponse
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@router.get("/showcase/projects")
async def showcase_projects():
    """Public list of projects that have been deployed. No code paths exposed."""
    projects_path = Path(PROJECTS_DIR)
    if not projects_path.exists():
        return []
    out = []
    for entry in sorted(projects_path.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        deploy_url = await _detect_deploy_url(entry)
        if not deploy_url:
            continue
        deploy_session_id = await _find_deploy_session(str(entry.resolve()), deploy_url)

        project_type = "price-game"
        claude_md = entry / "CLAUDE.md"
        if claude_md.exists():
            try:
                content = claude_md.read_text(encoding="utf-8", errors="replace")
                if "Entropy" in content or "IEntropyConsumer" in content:
                    project_type = "entropy-game"
                elif "Custom Game" in content:
                    project_type = "custom-game"
            except Exception:
                pass

        out.append({
            "id": entry.name,
            "name": entry.name.replace("-", " ").title(),
            "deploy_url": deploy_url,
            "deploy_session_id": deploy_session_id,
            "project_type": project_type,
        })
    return out


def _project_dir_for_session(working_dir: str) -> Path | None:
    """Return the project directory if `working_dir` is a project under PROJECTS_DIR."""
    if not working_dir:
        return None
    try:
        wd = Path(working_dir).resolve()
        root = Path(PROJECTS_DIR).resolve()
        if wd == root or root not in wd.parents:
            return None
        # The project dir is the immediate child of PROJECTS_DIR
        rel = wd.relative_to(root)
        first = rel.parts[0] if rel.parts else None
        if not first:
            return None
        return root / first
    except Exception:
        return None


@router.get("/showcase/sessions/{session_id}")
async def showcase_get_session(session_id: str):
    """Public read-only session view, gated to projects that have a deploy URL."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    project_dir = _project_dir_for_session(session.get("working_dir", ""))
    if not project_dir or not project_dir.exists() or not await _detect_deploy_url(project_dir):
        raise HTTPException(status_code=404, detail="Session not available")
    return serialize_doc(session)


@router.get("/showcase/sessions/{session_id}/chunks")
async def showcase_get_chunks(session_id: str):
    """Public read-only chunks for a showcase session."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    project_dir = _project_dir_for_session(session.get("working_dir", ""))
    if not project_dir or not project_dir.exists() or not await _detect_deploy_url(project_dir):
        raise HTTPException(status_code=404, detail="Session not available")
    chunks = await get_chunks_for_session(session_id)
    return [serialize_doc(c) for c in chunks]


@router.get("/admin/sessions")
async def admin_list_sessions():
    sessions = await list_sessions()
    return [serialize_doc(s) for s in sessions]


@router.get("/admin/sessions/{session_id}")
async def admin_get_session(session_id: str):
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return serialize_doc(session)


@router.get("/admin/sessions/{session_id}/chunks")
async def admin_get_chunks(session_id: str):
    chunks = await get_chunks_for_session(session_id)
    return [serialize_doc(c) for c in chunks]


