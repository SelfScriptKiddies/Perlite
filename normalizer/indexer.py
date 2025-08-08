"""
High-level orchestration:
- Process a single file (normalize + headings + links)
- Build backlinks
- Write metadata.json
"""
import json
from pathlib import Path
from typing import List, Dict
from .links import Resolver, is_md, WIKI_LINK, MD_LINK
from .parse import extract_headings, parse_frontmatter_and_tags

def process_file(p: Path, R: Resolver) -> Dict:
    rel = R.rel_from_root(p)
    original = p.read_text(encoding="utf-8", errors="ignore")

    fm, tags, aliases, body0 = parse_frontmatter_and_tags(original)

    stage1 = R.normalize_md_links_to_wikilinks(p, body0)
    norm   = R.normalize_wikilinks_in_text(p, stage1)

    if norm != body0:
        if body0 is not original:
            head_len = len(original) - len(body0)
            new_text = original[:head_len] + norm
        else:
            new_text = norm
        p.write_text(new_text, encoding="utf-8")

    headings = extract_headings(norm.splitlines())

    links = []
    # wikilinks (notes + anchors) — skip attachments (!)
    for m in WIKI_LINK.finditer(norm):
        bang = m.group("bang")
        if bang == "!":
            continue
        body = m.group("body")
        display = None
        target_part = body
        if "|" in body:
            target_part, display = body.split("|", 1)

        text_path, meta_rel_with_md = R.resolve_target_for_text_and_meta(p, body)
        if not meta_rel_with_md:
            continue
        # only keep links that actually point to .md files
        if not (R.ROOT / meta_rel_with_md).exists():
            continue

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

    # pure anchor markdown links [text](#PDF)
    for m in MD_LINK.finditer(norm):
        url = m.group("url").strip()
        if url.startswith("#"):
            anchor = url
            display = m.group("text").strip() or anchor.lstrip("#")
            links.append({
                "link": anchor,
                "relativePath": rel,
                "cleanLink": Path(rel).stem,
                "displayText": display
            })

    if links:
        uniq, seen = [], set()
        for L in links:
            key = (L.get("link"), L.get("relativePath"), L.get("displayText"))
            if key not in seen:
                uniq.append(L); seen.add(key)
        links = uniq

    item: Dict = {"fileName": p.stem, "relativePath": rel}
    if tags:      item["tags"] = tags
    if aliases:   item["aliases"] = aliases
    if fm:        item["frontmatter"] = fm
    if headings:  item["headings"] = headings
    if links:     item["links"] = links
    return item

def build_metadata(root: Path, output: Path, shortest_mode: str = "vault") -> List[Dict]:
    root = root.resolve()
    R = Resolver(root=root, shortest_mode=shortest_mode)
    all_md = [p for p in root.rglob("*") if p.is_file() and is_md(p)]

    items = [process_file(p, R) for p in all_md]

    # backlinks
    forward: Dict[str, List[str]] = {}
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

    output.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return items
