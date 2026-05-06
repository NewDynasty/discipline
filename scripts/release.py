#!/usr/bin/env python3
"""
release.py — 一键版本发布：tag + changelog + commit
用法:
  python3 release.py                    # 自动 bump patch (0.1.0 → 0.1.1)
  python3 release.py minor              # bump minor (0.1.0 → 0.2.0)
  python3 release.py major              # bump major (0.1.0 → 1.0.0)
  python3 release.py --dry-run          # 预览不执行
  python3 release.py --init             # 初始版本 (v0.1.0)
"""

import subprocess
import sys
import re
import os

def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if check and r.returncode != 0:
        print(f"❌ Command failed: {cmd}\n{r.stderr}")
        sys.exit(1)
    return r.stdout.strip()

def get_latest_tag(cwd):
    out = run("git tag --sort=-v:refname | head -1", cwd=cwd)
    return out if out else None

def bump_version(tag, part="patch"):
    if not tag:
        return "v0.1.0"
    # strip leading v
    v = tag.lstrip("v")
    parts = v.split(".")
    while len(parts) < 3:
        parts.append("0")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    if part == "major":
        return f"v{major+1}.0.0"
    elif part == "minor":
        return f"v{major}.{minor+1}.0"
    else:
        return f"v{major}.{minor}.{patch+1}"

def main():
    dry_run = "--dry-run" in sys.argv
    init_mode = "--init" in sys.argv
    part = "patch"
    for arg in sys.argv[1:]:
        if arg in ("major", "minor", "patch"):
            part = arg

    cwd = os.getcwd()
    project = os.path.basename(cwd)

    # Check for uncommitted changes
    status = run("git status --porcelain", cwd=cwd)
    if status and not dry_run:
        print(f"⚠️  Uncommitted changes detected. Commit or stash first.")
        print(status[:500])
        sys.exit(1)

    # Get current tag
    current = get_latest_tag(cwd)
    if init_mode:
        new_tag = "v0.1.0"
    else:
        new_tag = bump_version(current, part)

    print(f"📦 {project}: {current or 'none'} → {new_tag}")

    if dry_run:
        # Preview changelog
        out = run(f"git-cliff --tag {new_tag} --unreleased --strip header", cwd=cwd, check=False)
        print(f"\n📝 Preview:\n{out}")
        return

    # Generate CHANGELOG
    run(f"git-cliff --tag {new_tag} -o CHANGELOG.md", cwd=cwd)
    print(f"✅ CHANGELOG.md updated")

    # Commit CHANGELOG
    run("git add CHANGELOG.md", cwd=cwd)
    run(f'git commit -m "chore(release): prepare for {new_tag}" --no-verify', cwd=cwd)
    print(f"✅ Committed")

    # Create tag
    run(f"git tag {new_tag}", cwd=cwd)
    print(f"✅ Tagged {new_tag}")

    # Show summary
    print(f"\n🎉 Released {new_tag}!")
    print(f"   git push && git push --tags  # to publish")

if __name__ == "__main__":
    main()
