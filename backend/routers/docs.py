"""Docs API — Obsidian vault browsing, search, projects, and docs SPA."""

import glob
import os
import re

import markdown as md_lib
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import HTMLResponse

from deps import OBSIDIAN_VAULT, PORTAL_DIR, VAULT_REGISTRY

router = APIRouter(tags=["docs"])

# --- Docs directories from registry ---
_docs_cfg = VAULT_REGISTRY.get("docs", {})
_dirs_list = _docs_cfg.get("dirs", ["Bookmarks", "Kanban", "Notes", "People", "PlanPipeline", "Research", "TaskLog", "Workspace"])
DOCS_DIRS = {name: os.path.join(OBSIDIAN_VAULT, name) for name in _dirs_list}

# --- Projects from registry ---
_proj_cfg = VAULT_REGISTRY.get("projects", {})
_proj_dirs = _proj_cfg.get("dirs", ["Notes"])
_proj_pattern = _proj_cfg.get("pattern", "*-progress.md")
PROJECTS_DIRS = [os.path.join(OBSIDIAN_VAULT, d) for d in _proj_dirs]
# Helpers
# ---------------------------------------------------------------------------

def _safe_path(requested_path: str) -> str | None:
    """Resolve path and ensure it's within OBSIDIAN_VAULT."""
    full = os.path.normpath(os.path.join(OBSIDIAN_VAULT, requested_path))
    if not full.startswith(os.path.normpath(OBSIDIAN_VAULT)):
        return None
    return full


PROJECTS_DIR = os.path.join(OBSIDIAN_VAULT, "Notes")


def _parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter from markdown."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in text[3:end].strip().split("\n"):
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        elif v.isdigit():
            v = int(v)
        fm[k] = v
    return fm


def _extract_md_section(text: str, heading: str) -> str:
    """Extract content under a ## heading."""
    m = re.search(
        rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@router.get("/api/docs/tree")
def docs_tree():
    """Return folder tree with file counts."""
    result = []
    for name, path in DOCS_DIRS.items():
        if not os.path.isdir(path):
            continue
        files = []
        for f in sorted(glob.glob(os.path.join(path, "*.md"))):
            fname = os.path.splitext(os.path.basename(f))[0]
            mtime = os.path.getmtime(f)
            files.append({"name": fname, "mtime": mtime})
        files.sort(key=lambda x: x["mtime"], reverse=True)
        for f in files:
            del f["mtime"]
        result.append({"folder": name, "files": files})
    return result


@router.get("/api/docs/content")
def docs_content(path: str = ""):
    """Read and render a markdown file. path is relative to vault root."""
    full = _safe_path(path)
    if not full or not os.path.isfile(full):
        raise HTTPException(404, "文件不存在")
    if not full.endswith(".md"):
        full += ".md"

    try:
        with open(full, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        raise HTTPException(500, str(e))

    # Parse frontmatter
    title = os.path.splitext(os.path.basename(full))[0]
    tags: list[str] = []
    date_str = ""
    content_raw = raw
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', raw, re.DOTALL)
    if fm_match:
        content_raw = fm_match.group(2)
        fm_text = fm_match.group(1)
        tag_m = re.search(r'tags:\s*\[(.*?)\]', fm_text)
        if tag_m:
            tags = [t.strip().strip('"\'') for t in tag_m.group(1).split(",") if t.strip()]
        date_m = re.search(r'date:\s*["\']?(\d{4}-\d{2}-\d{2})', fm_text)
        if date_m:
            date_str = date_m.group(1)

    # Render markdown to HTML
    html_content = md_lib.markdown(
        content_raw,
        extensions=["extra", "codehilite", "toc", "tables", "fenced_code"],
        output_format="html5",
    )

    return {
        "title": title,
        "tags": tags,
        "date": date_str,
        "html": html_content,
        "path": path,
    }


@router.get("/api/docs/search")
def docs_search(q: str = ""):
    """Full-text search across all docs dirs."""
    if not q or len(q) < 2:
        return []
    results = []
    ql = q.lower()
    for name, dir_path in DOCS_DIRS.items():
        if not os.path.isdir(dir_path):
            continue
        for f in glob.glob(os.path.join(dir_path, "*.md")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    content = fh.read(10000).lower()
                if ql in content or ql in os.path.basename(f).lower():
                    fname = os.path.splitext(os.path.basename(f))[0]
                    results.append({
                        "title": fname,
                        "folder": name,
                        "path": os.path.relpath(f, OBSIDIAN_VAULT),
                    })
            except Exception:
                pass
    return results[:20]


@router.get("/api/projects")
def get_projects():
    """Return all projects from vault-registry configured progress files."""
    projects = []
    for proj_dir in PROJECTS_DIRS:
        for fpath in sorted(glob.glob(os.path.join(proj_dir, _proj_pattern))):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    text = f.read()
                meta = _parse_frontmatter(text)
                if not meta:
                    continue
                # Extract description from 项目定位 section
                desc = _extract_md_section(text, "项目定位").strip("- \n") or ""
                if not desc or desc == "---":
                    # Fallback: use first non-empty, non-heading line after frontmatter
                    for line in text.split("\n"):
                        line = line.strip()
                        if line.startswith("---") or line.startswith("#") or line.startswith(">") or not line:
                            continue
                        desc = line
                        break
                # Extract done/todo summaries
                done_sec = ""
                for h in ["已完成 ✅", "已完成", "当前状态", "核心结论"]:
                    done_sec = _extract_md_section(text, h)
                    if done_sec:
                        break
                done_items = [re.sub(r"^\s*[-*]\s*", "", l).strip() for l in done_sec.split("\n") if re.match(r"^\s*[-*]\s+", l)]
                todo_sec = _extract_md_section(text, "待办 📋") or _extract_md_section(text, "待办")
                todo_items = [re.sub(r"^\s*[-*]\s*", "", l).strip() for l in todo_sec.split("\n") if re.match(r"^\s*[-*]\s+", l)]
                # Title from first heading
                title_m = re.search(r"^# (.+)$", text, re.MULTILINE)
                meta["title"] = title_m.group(1) if title_m else meta.get("project", "")
                meta["description"] = desc
                meta["done"] = done_items[:8]
                meta["todo"] = todo_items[:6]
                projects.append(meta)
            except Exception:
                pass
    return {"projects": projects}


# ---------------------------------------------------------------------------
# Docs SPA page routes
# ---------------------------------------------------------------------------

@router.get("/docs")
@router.get("/docs/")
@router.get("/docs/{full_path:path}")
def serve_docs(full_path: str = ""):
    html_path = os.path.join(PORTAL_DIR, "docs.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return JSONResponse({"error": "Docs UI not found"}, status_code=404)


# ---------------------------------------------------------------------------
# Graph SPA page route
# ---------------------------------------------------------------------------

@router.get("/graph")
@router.get("/graph/")
def serve_graph():
    html_path = os.path.join(PORTAL_DIR, "graph.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return JSONResponse({"error": "Graph UI not found"}, status_code=404)
