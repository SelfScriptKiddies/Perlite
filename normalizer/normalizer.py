#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Normalize an Obsidian vault for Perlite and generate metadata.json.

Features:
- Convert Markdown links [text](path) to Obsidian wikilinks [[...]] / ![[...]]
  (but keep pure anchor links like (#PDF) intact).
- Normalize wikilinks (with alias and #anchor) to absolute, repo-rooted paths
  without ".md" in the visible link target; preserve alias and anchor.
- Extract headings (ATX and Setext).
- Parse minimal YAML frontmatter (tags, aliases, any simple k:v) and merge inline #tags.
- Build links and backlinks in the format Perlite demo expects, including
  anchor-only links with cleanLink/displayText.
- Write metadata.json at the vault root.
"""

import json
import os, re
import sys
from pathlib import Path

# ----------------------------- Config ---------------------------------------

ROOT = Path(sys.argv[1]).resolve()
OUT = ROOT / "metadata.json"

MD_EXTS  = {".md", ".markdown", ".mdown"}
IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf"}
ASSET_EXTS = IMG_EXTS | {".mp4", ".m4a", ".webm", ".mov", ".mp3", ".wav", ".ogg"}

# ----------------------------- Helpers --------------------------------------

def is_md(p: Path) -> bool:
    return p.suffix.lower() in MD_EXTS

def rel_from_root(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()

def strip_md_ext(path_str: str) -> str:
    p = Path(path_str)
    if p.suffix.lower() in MD_EXTS:
        return p.with_suffix("").as_posix()
    return p.as_posix()

# Will be filled after ALL_MD is computed
BASENAME_INDEX: dict[str, list[Path]] = {}

def find_target_path(current_file: Path, raw: str) -> str:
    """
    Resolve an Obsidian/Markdown link target to an absolute path from vault root,
    WITHOUT the .md extension. Keep #anchor if present.
    Accepted inputs:
      - 'Note.md', './Note.md', '../dir/Note.md'
      - 'dir/Note.md#anchor'
      - 'dir/Note' or 'Note'
    """
    anchor = None
    if "#" in raw:
        raw, anchor = raw.split("#", 1)

    raw = raw.strip()
    if raw == "":
        return "#" + anchor if anchor else ""

    # Treat absolute FS paths as repo-rooted (strip leading slash)
    candidate = Path(raw)
    if candidate.is_absolute():
        candidate = Path(str(candidate).lstrip("/"))

    # Try relative to the current file's directory
    base = current_file.parent
    abs_path = (base / candidate).resolve()
    if abs_path.exists():
        out = strip_md_ext(rel_from_root(abs_path))
    else:
        # Fallback: try basename index (unique match by name or stem)
        out = None
        bn = candidate.name
        matches = BASENAME_INDEX.get(bn, []) + BASENAME_INDEX.get(strip_md_ext(bn), [])
        # de-duplicate
        uniq = list(dict.fromkeys(matches))
        if len(uniq) == 1:
            out = strip_md_ext(rel_from_root(uniq[0]))
        elif len(uniq) > 1:
            # ambiguous → keep as typed (no .md)
            out = strip_md_ext(candidate.as_posix())
        else:
            out = strip_md_ext(candidate.as_posix())

    if anchor:
        out += f"#{anchor}"
    return out

def to_rel(base: Path, abs_file: Path) -> str:
    """Return POSIX relative path from base to abs_file."""
    return os.path.relpath(abs_file, start=base).replace("\\", "/")

def resolve_asset_for_text(current_file: Path, raw: str) -> str:
    """
    Resolve attachment/media path for wikilink TEXT:
    - Always return a path RELATIVE to current file's folder (extension kept).
    - Accept both paths typed relative to the note and vault-rooted paths.
    - If no extension provided, try common asset extensions.
    """
    target = raw.split("|", 1)[0].strip()
    if not target:
        return raw

    base = current_file.parent
    cand = Path(target)

    # Treat absolute FS paths as vault-rooted
    if cand.is_absolute():
        cand = Path(str(cand).lstrip("/"))

    def exist_rel(p: Path) -> Path | None:
        ap = (base / p).resolve()
        return ap if ap.exists() and ap.is_file() else None

    def exist_root(p: Path) -> Path | None:
        ap = (ROOT / p).resolve()
        return ap if ap.exists() and ap.is_file() else None

    # Case A: target has extension -> try relative first, then vault-rooted
    if cand.suffix:
        found = exist_rel(cand)
        if found:
            return to_rel(base, found)
        found = exist_root(cand)
        if found:
            return to_rel(base, found)
        # fallback: leave as typed
        return cand.as_posix()

    # Case B: no extension -> try same dir with known asset extensions
    for ext in ASSET_EXTS:
        p = exist_rel(cand.with_suffix(ext))
        if p:
            return to_rel(base, p)

    # Try vault-rooted with known extensions
    for ext in ASSET_EXTS:
        p = exist_root(cand.with_suffix(ext))
        if p:
            return to_rel(base, p)

    # Wider fallback: search under ROOT for basename with any asset ext,
    # choose the one with shortest relative path (closest)
    candidates = []
    name = cand.name
    for f in ROOT.rglob(name + ".*"):
        if f.suffix.lower() in ASSET_EXTS and f.is_file():
            candidates.append(f)
    if candidates:
        candidates.sort(key=lambda f: len(os.path.relpath(f, start=base)))
        return to_rel(base, candidates[0])

    # Last resort: keep as typed
    return cand.as_posix()

# ------------------------- Scan vault files ----------------------------------

ALL_MD: list[Path] = sorted([p for p in ROOT.rglob("*") if p.is_file() and is_md(p)])
for p in ALL_MD:
    BASENAME_INDEX.setdefault(p.name, []).append(p)
    BASENAME_INDEX.setdefault(p.stem, []).append(p)

# ------------------------- Headings parsing ----------------------------------

ATX       = re.compile(r'^(?P<hashes>#{1,6})\s*(?P<text>.+?)\s*#*\s*$')
SETEXT_H1 = re.compile(r'^\s*={3,}\s*$')
SETEXT_H2 = re.compile(r'^\s*-{3,}\s*$')

def extract_headings(lines: list[str]) -> list[dict]:
    """
    Return a list of dicts: {heading, level} from ATX and Setext headings.
    """
    headings = []
    prev_line = ""
    for line in lines:
        m = ATX.match(line)
        if m:
            level = len(m.group("hashes"))
            text = m.group("text").strip()
            if text:
                headings.append({"heading": text, "level": level})
        else:
            # Setext: use the previous line as the heading text
            if SETEXT_H1.match(line):
                t = prev_line.strip()
                if t:
                    headings.append({"heading": t, "level": 1})
            elif SETEXT_H2.match(line):
                t = prev_line.strip()
                if t:
                    headings.append({"heading": t, "level": 2})
        prev_line = line
    return headings

# --------------------- Frontmatter + inline tags -----------------------------

FM_START    = re.compile(r'^\s*---\s*$')
FM_END      = re.compile(r'^\s*(---|\.\.\.)\s*$')
INLINE_TAG = re.compile(r'(?<!\w)#([A-Za-z0-9/_-]+)')  # #tag-test (no whitespace, supports hyphens etc.)

def parse_frontmatter_and_tags(text: str):
    """
    Extract minimal YAML frontmatter (tags, aliases, simple k:v) and inline #tags.
    Returns: (frontmatter_dict, tags_list, aliases_list, body_without_frontmatter)
    """
    lines = text.splitlines()
    fm = {}
    tags, aliases = [], []
    body_start = 0

    # Detect frontmatter block
    if lines and FM_START.match(lines[0]):
        i = 1
        block = []
        while i < len(lines) and not FM_END.match(lines[i]):
            block.append(lines[i])
            i += 1
        body_start = i + 1 if i < len(lines) else 0

        # Minimal parser for tags/aliases lists and simple k:v
        cur_key = None
        for ln in block:
            # keys "tags:" or "aliases:"
            if re.match(r'^\s*(tags|aliases)\s*:\s*$', ln):
                cur_key = ln.split(':')[0].strip()
                fm[cur_key] = []
                continue
            # items: "- value"
            m = re.match(r'^\s*-\s*(.+?)\s*$', ln)
            if m and cur_key in ('tags', 'aliases'):
                fm[cur_key].append(m.group(1))
                continue
            # other k:v pairs (very simple)
            kv = re.match(r'^\s*([A-Za-z0-9_.-]+)\s*:\s*(.*)$', ln)
            if kv:
                key, val = kv.group(1), kv.group(2)
                fm[key] = val
                cur_key = None

        tags    = list(dict.fromkeys(fm.get('tags', [])))
        aliases = list(dict.fromkeys(fm.get('aliases', [])))

    body = "\n".join(lines[body_start:]) if body_start else text

    # Remove links before scanning inline #tags
    body_for_tags = WIKI_LINK.sub(' ', body)
    body_for_tags = MD_LINK.sub(' ', body_for_tags)

    inline = [m.group(1) for m in INLINE_TAG.finditer(body_for_tags)]
    if inline:
        merged = tags + [t for t in inline if t not in tags]
        tags = list(dict.fromkeys(merged))

    return (fm if fm else {}, tags, aliases, body)

# ----------------------------- Shortest target logic -------------------------

# Modes:
# - "vault": choose shortest unique suffix from vault root (no "../")
# - "relative": choose shortest actual relative path from current file (with "../")
SHORTEST_MODE = "vault"  # or "relative"

def collect_conflict_paths_for_basename(stem_or_name: str) -> list[Path]:
    """Return all candidate files that share given stem or name (from BASENAME_INDEX)."""
    # We index by both .name and .stem; just union the lists
    return list(dict.fromkeys(
        BASENAME_INDEX.get(stem_or_name, []) +
        BASENAME_INDEX.get(Path(stem_or_name).stem, [])
    ))

def shortest_suffix_from_vault(target_abs_no_ext: str) -> str:
    """
    Return the shortest *repo-root relative* suffix to use inside [[...]].
    Rules:
      - Always relative to vault root (no leading slash).
      - If the note is in the root folder -> 'Note'
      - Otherwise include at least one directory: 'dir/Note'
      - If there are conflicts, extend the suffix until unique.
    """
    target_path = Path(target_abs_no_ext)                  # e.g. 'Untitled/My Bro'
    parts = target_path.parts                              # ('Untitled','My Bro')
    stem = target_path.name                                # 'My Bro'

    # Collect all conflicts for this basename (by name and stem)
    conflicts = list(dict.fromkeys(
        BASENAME_INDEX.get(stem, []) +
        BASENAME_INDEX.get(Path(stem).stem, [])
    ))
    # Normalize conflict paths to repo-rooted no-ext strings
    conflict_noext = {strip_md_ext(rel_from_root(p)) for p in conflicts}

    # Helper: does suffix uniquely match the target?
    def is_unique_suffix(sfx: str) -> bool:
        matches = [c for c in conflict_noext if c.endswith('/' + sfx) or c == sfx]
        return len(matches) == 1 and matches[0] == target_abs_no_ext

    # If the file lives in the root folder, we *can* use just 'stem'
    if len(parts) == 1:
        return stem

    # Otherwise, we must include at least one directory.
    # Build candidates from shortest (#segments=2) to longer: ['Untitled/My Bro', ...]
    candidates = []
    for take in range(2, len(parts) + 1):
        cand = Path(*parts[-take:]).as_posix()
        candidates.append(cand)
    candidates.sort(key=lambda s: (s.count('/') + 1, len(s)))  # fewest segments, then chars

    # First, try the minimal 2-segment suffix (parent/stem). If unique -> done.
    if is_unique_suffix(candidates[0]):
        return candidates[0]

    # If not unique (or there are deeper dirs), try longer suffixes
    for cand in candidates[1:]:
        if is_unique_suffix(cand):
            return cand

    # Fallback: full path from root (still no '.md')
    return target_abs_no_ext

def shortest_relative_from_current(current_file: Path, target_abs_no_ext: str) -> str:
    """
    Real relative path (with ../) from current file's folder to the target (no .md).
    This can be even shorter in characters, but may be less friendly for Perlite routing.
    """
    base = current_file.parent
    target = ROOT / (target_abs_no_ext + ".md")
    try:
        rel = Path(Path.relpath(target, start=base)).with_suffix("")  # strip .md
    except Exception:
        rel = Path(target_abs_no_ext)
    return rel.as_posix()

# ---------------------- Link normalization ----------------------------------

# Markdown link: [text](url)
MD_LINK   = re.compile(r'(!?)\[(?P<text>[^\]]*)\]\((?P<url>[^)]+)\)')
# Obsidian wikilink: [[body]] or ![[body]]
WIKI_LINK = re.compile(r'(?P<bang>!?)\[\[(?P<body>.+?)\]\]')

def normalize_md_links_to_wikilinks(current_file: Path, text: str) -> str:
    """
    Convert standard Markdown links to wikilinks where appropriate.
    Keep external links and pure anchor links untouched.
    """
    def repl(m):
        bang = m.group(1)  # '!' means image
        url  = m.group("url").strip()

        # Keep pure anchor links as-is: [text](#Heading)
        if url.startswith("#"):
            return m.group(0)

        # Keep external links as-is (http:, https:, mailto:, tel:, //, etc.)
        if re.match(r'^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)', url):
            return m.group(0)

        # Convert to wikilink with resolved absolute path (no .md)
        target = find_target_path(current_file, url)

        # Images / attachments — ![[...]]
        suffix = Path(url).suffix.lower()
        if bang == "!" or suffix in IMG_EXTS or suffix in ASSET_EXTS:
            asset_rel = resolve_asset_for_text(current_file, url)
            return f"![[{asset_rel}]]"

        return f"[[{target}]]"

    return MD_LINK.sub(repl, text)

def resolve_target_for_text_and_meta(current_file: Path, raw: str):
    """
    Return:
      - text_target_no_ext_with_optional_anchor (for wikilink body)
      - meta_relpath_with_md_no_anchor       (for metadata.links.relativePath)
    """
    # Split alias (|) and #anchor
    if "|" in raw:
        target, _alias = raw.split("|", 1)
    else:
        target = raw

    anchor = None
    if "#" in target:
        target, anchor = target.split("#", 1)

    target = target.strip()
    if not target:
        return (raw, None)

    # Resolve to absolute (repo-rooted) path WITHOUT .md
    abs_no_ext = find_target_path(current_file, target)  # may contain #anchor
    abs_no_ext_clean = abs_no_ext.split("#", 1)[0]

    # Choose the "shortest" textual reference (no .md) according to mode
    if SHORTEST_MODE == "relative":
        shortest_no_ext = shortest_relative_from_current(current_file, abs_no_ext_clean)
    else:
        shortest_no_ext = shortest_suffix_from_vault(abs_no_ext_clean)

    # Add back #anchor for the wikilink text if it existed
    if anchor:
        text_target = f"{shortest_no_ext}#{anchor}"
    else:
        text_target = shortest_no_ext

    # For metadata we always store the full, absolute repo-rooted path WITH .md (no anchor)
    meta_with_md = abs_no_ext_clean + ".md"

    return (text_target, meta_with_md)

def normalize_wikilinks_in_text(current_file: Path, text: str) -> str:
    def repl(m):
        bang  = m.group("bang")
        body  = m.group("body")
        alias = None
        if "|" in body:
            target_part, alias = body.split("|", 1)
        else:
            target_part = body

        if bang == "!":
            # ATTACHMENT: keep path RELATIVE to current file, preserve extension and alias
            asset_rel = resolve_asset_for_text(current_file, target_part)
            return f"![[{asset_rel}|{alias}]]" if alias is not None else f"![[{asset_rel}]]"

        # NOTE LINK (markdown): use previous logic (root-relative shortest)
        text_target, _meta = resolve_target_for_text_and_meta(current_file, body)
        if not text_target or text_target.strip() == body.strip():
            return m.group(0)
        return f"[[{text_target}|{alias}]]" if alias is not None else f"[[{text_target}]]"
    return WIKI_LINK.sub(repl, text)

# ------------------------------ Processing ----------------------------------

def process_file(p: Path) -> dict:
    rel = rel_from_root(p)
    original = p.read_text(encoding="utf-8", errors="ignore")

    # Parse frontmatter + inline tags from the original text
    fm, tags, aliases, body0 = parse_frontmatter_and_tags(original)

    # Normalize links in the BODY (do not touch frontmatter)
    stage1 = normalize_md_links_to_wikilinks(p, body0)   # md -> wikilinks (except pure anchors)
    norm   = normalize_wikilinks_in_text(p, stage1)      # wikilinks -> absolute (keep alias/anchor)

    # If changed, write back file, preserving frontmatter if present
    if norm != body0:
        if body0 is not original:
            # There was a frontmatter block, rebuild file: header + normalized body
            head_len = len(original) - len(body0)
            new_text = original[:head_len] + norm
        else:
            new_text = norm
        p.write_text(new_text, encoding="utf-8")

    # Extract headings from the normalized body
    headings = extract_headings(norm.splitlines())

    # Build outgoing links list from:
    #  (1) wikilinks (files and anchors)
    #  (2) pure anchor markdown links [text](#Anchor)
    links = []

    # (1) Wikilinks
    for m in WIKI_LINK.finditer(norm):
        bang = m.group("bang")
        body = m.group("body")
        display = None
        target_part = body
        if "|" in body:
            target_part, display = body.split("|", 1)

        text_path, meta_rel_with_md = resolve_target_for_text_and_meta(p, body)
        if not meta_rel_with_md:
            continue

        # SKIP attachments: only keep links to existing .md notes
        if bang == "!":
            continue
        if not (ROOT / meta_rel_with_md).exists():
            # it's likely an asset (png/webp/pdf/mp4) that we converted to ![[...]] in text
            # but metadata should not list it
            continue

        # Link key:
        # - If target includes #anchor, "link" is "#anchor", plus cleanLink=file name (like demo)
        # - Otherwise "link" is the base filename (no ext)
        if "#" in target_part:
            anchor = "#" + target_part.split("#", 1)[1]
            entry = {
                "link": anchor,
                "relativePath": meta_rel_with_md,
                "cleanLink": Path(meta_rel_with_md).stem
            }
            if display:
                entry["displayText"] = display
        else:
            basename = Path(target_part).name
            entry = {
                "link": basename,
                "relativePath": meta_rel_with_md
            }
            if display:
                entry["displayText"] = display

        links.append(entry)

    # (2) Pure anchor markdown links
    for m in MD_LINK.finditer(norm):
        url = m.group("url").strip()
        if url.startswith("#"):
            anchor   = url  # e.g., "#PDF"
            display  = m.group("text").strip() or anchor.lstrip("#")
            entry = {
                "link": anchor,
                "relativePath": rel,                 # current file
                "cleanLink": Path(rel).stem,
                "displayText": display
            }
            links.append(entry)

    # Deduplicate links (by link/relativePath/displayText)
    if links:
        uniq, seen = [], set()
        for L in links:
            key = (L.get("link"), L.get("relativePath"), L.get("displayText"))
            if key not in seen:
                uniq.append(L)
                seen.add(key)
        links = uniq

    item: dict = {
        "fileName": p.stem,
        "relativePath": rel,
    }
    if tags:
        item["tags"] = tags
    if aliases:
        item["aliases"] = aliases
    if fm:
        item["frontmatter"] = fm
    if headings:
        item["headings"] = headings
    if links:
        item["links"] = links

    return item

def main():
    items = [process_file(p) for p in ALL_MD]

    # Build backlinks: map each target (relativePath with .md) to list of sources
    forward: dict[str, list[str]] = {}
    for it in items:
        for ln in it.get("links", []):
            forward.setdefault(ln["relativePath"], []).append(it["relativePath"])

    for it in items:
        srcs = forward.get(it["relativePath"], [])
        if srcs:
            this_name = Path(it["relativePath"]).stem
            it["backlinks"] = [
                {
                    "fileName": Path(src).stem,
                    "link": this_name,
                    "relativePath": src,
                    "displayText": this_name
                }
                for src in srcs
            ]

    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {rel_from_root(OUT)} with {len(items)} items")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: normalize_and_index.py <vault_root>", file=sys.stderr)
        sys.exit(1)
    main()
