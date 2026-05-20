#!/usr/bin/env python3
"""
generate.py — Build opencode.jsonc from the registry.

Usage:
  python3 scripts/generate.py                    # all enabled items
  python3 scripts/generate.py --skills lims-analysis,qms-investigation
  python3 scripts/generate.py --blueprints deviation-investigation
  python3 scripts/generate.py --mcps lims,qms,rosetta
  python3 scripts/generate.py --model ollama/qwen3:30b
  python3 scripts/generate.py --dry-run          # print config without writing

Called by the Lattice Manager on /launch and by the lattice shell script on startup.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
REGISTRY = ROOT / "registry"
OUT = ROOT / "opencode.jsonc"


def parse_frontmatter(path: Path) -> dict:
    """Read YAML-style frontmatter between --- delimiters."""
    text = path.read_text()
    if not text.startswith("---"):
        return {}
    end = text.index("---", 3)
    fm_text = text[3:end].strip()
    meta = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta


def load_skills(selected: list[str] | None) -> list[Path]:
    paths = sorted((REGISTRY / "skills").glob("*.md"))
    result = []
    for p in paths:
        fm = parse_frontmatter(p)
        name_slug = p.stem
        enabled = fm.get("enabled", "true").lower() == "true"
        if selected is not None:
            if name_slug in selected:
                result.append(p)
        elif enabled:
            result.append(p)
    return result


def load_blueprints(selected: list[str] | None) -> list[Path]:
    paths = sorted((REGISTRY / "blueprints").glob("*.md"))
    result = []
    for p in paths:
        fm = parse_frontmatter(p)
        name_slug = p.stem
        enabled = fm.get("enabled", "true").lower() == "true"
        if selected is not None:
            if name_slug in selected:
                result.append(p)
        elif enabled:
            result.append(p)
    return result


def load_mcps(selected: list[str] | None) -> dict:
    mcps_def = json.loads((REGISTRY / "mcps.json").read_text())
    if selected is None:
        return mcps_def
    return {k: v for k, v in mcps_def.items() if k in selected}


def estimate_tokens(paths: list[Path]) -> int:
    """Rough estimate: 1 token per 4 chars."""
    total = 0
    for p in paths:
        total += len(p.read_text()) // 4
    return total


def build_config(skills: list[Path], blueprints: list[Path], mcps: dict, model: str) -> dict:
    instructions = [str(REGISTRY / "context.md")]
    for p in skills + blueprints:
        instructions.append(str(p.relative_to(ROOT)))

    mcp_section = {}
    for name, defn in mcps.items():
        mcp_section[name] = {
            "type": "local",
            "command": defn["command"],
            "enabled": True,
        }

    return {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "instructions": instructions,
        "mcp": mcp_section,
        "server": {
            "hostname": "0.0.0.0",
            "port": 4000,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Generate opencode.jsonc from Lattice registry")
    parser.add_argument("--skills",     help="Comma-separated skill slugs (default: all enabled)")
    parser.add_argument("--blueprints", help="Comma-separated blueprint slugs (default: all enabled)")
    parser.add_argument("--mcps",       help="Comma-separated MCP names (default: all)")
    parser.add_argument("--model",      default=None, help="Model string override")
    parser.add_argument("--dry-run",    action="store_true", help="Print config, do not write file")
    args = parser.parse_args()

    # Read model from .env if not specified
    model = args.model
    if not model:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("OLLAMA_MODEL="):
                    model = f"ollama/{line.split('=',1)[1].strip()}"
                elif line.startswith("OPENROUTER_MODEL=") and not model:
                    model = f"openrouter/{line.split('=',1)[1].strip()}"
        model = model or "ollama/qwen3:8b"

    skills_sel    = args.skills.split(",")     if args.skills     else None
    blueprints_sel = args.blueprints.split(",") if args.blueprints else None
    mcps_sel      = args.mcps.split(",")       if args.mcps       else None

    skills     = load_skills(skills_sel)
    blueprints = load_blueprints(blueprints_sel)
    mcps       = load_mcps(mcps_sel)

    config = build_config(skills, blueprints, mcps, model)
    token_est = estimate_tokens(skills + blueprints)

    output = json.dumps(config, indent=2)

    if args.dry_run:
        print(output)
        print(f"\n# Skills: {[p.stem for p in skills]}", file=sys.stderr)
        print(f"# Blueprints: {[p.stem for p in blueprints]}", file=sys.stderr)
        print(f"# MCPs: {list(mcps.keys())}", file=sys.stderr)
        print(f"# Estimated context tokens: ~{token_est:,}", file=sys.stderr)
        return

    OUT.write_text(output)
    print(f"Wrote {OUT.relative_to(ROOT)}")
    print(f"  Skills:     {[p.stem for p in skills]}")
    print(f"  Blueprints: {[p.stem for p in blueprints]}")
    print(f"  MCPs:       {list(mcps.keys())}")
    print(f"  Model:      {model}")
    print(f"  Est. tokens: ~{token_est:,}")


if __name__ == "__main__":
    main()
