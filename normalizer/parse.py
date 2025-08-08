"""
Parsing utilities:
- Headings extraction (ATX + Setext)
- Minimal frontmatter (tags, aliases, simple k:v)
- Inline #tags with link-stripping to avoid false positives
"""
import re
from typing import Tuple, List, Dict

# Basic patterns (duplicated here to avoid circular imports)
MD_LINK   = re.compile(r'(!?)\[(?P<text>[^\]]*)\]\((?P<url>[^)]+)\)')
WIKI_LINK = re.compile(r'(?P<bang>!?)\[\[(?P<body>.+?)\]\]')

ATX       = re.compile(r'^(?P<hashes>#{1,6})\s*(?P<text>.+?)\s*#*\s*$')
SETEXT_H1 = re.compile(r'^\s*={3,}\s*$')
SETEXT_H2 = re.compile(r'^\s*-{3,}\s*$')

FM_START  = re.compile(r'^\s*---\s*$')
FM_END    = re.compile(r'^\s*(---|\.\.\.)\s*$')
INLINE_TAG = re.compile(r'(?<!\w)#([A-Za-z0-9/_-]+)')

def extract_headings(lines: List[str]) -> List[Dict]:
    headings = []
    prev = ""
    for line in lines:
        m = ATX.match(line)
        if m:
            level = len(m.group("hashes"))
            text  = m.group("text").strip()
            if text:
                headings.append({"heading": text, "level": level})
        else:
            if SETEXT_H1.match(line):
                t = prev.strip()
                if t:
                    headings.append({"heading": t, "level": 1})
            elif SETEXT_H2.match(line):
                t = prev.strip()
                if t:
                    headings.append({"heading": t, "level": 2})
        prev = line
    return headings

def parse_frontmatter_and_tags(text: str) -> Tuple[Dict, list, list, str]:
    """
    Returns: (frontmatter_dict, tags_list, aliases_list, body_without_frontmatter)
    """
    lines = text.splitlines()
    fm = {}
    tags, aliases = [], []
    body_start = 0

    if lines and FM_START.match(lines[0]):
        i = 1
        block = []
        while i < len(lines) and not FM_END.match(lines[i]):
            block.append(lines[i]); i += 1
        body_start = i + 1 if i < len(lines) else 0

        cur_key = None
        for ln in block:
            if re.match(r'^\s*(tags|aliases)\s*:\s*$', ln):
                cur_key = ln.split(':')[0].strip()
                fm[cur_key] = []
                continue
            m = re.match(r'^\s*-\s*(.+?)\s*$', ln)
            if m and cur_key in ('tags', 'aliases'):
                fm[cur_key].append(m.group(1))
                continue
            kv = re.match(r'^\s*([A-Za-z0-9_.-]+)\s*:\s*(.*)$', ln)
            if kv:
                fm[kv.group(1)] = kv.group(2)
                cur_key = None

        tags    = list(dict.fromkeys(fm.get('tags', [])))
        aliases = list(dict.fromkeys(fm.get('aliases', [])))

    body = "\n".join(lines[body_start:]) if body_start else text

    # Strip links before scanning inline #tags
    body_for_tags = WIKI_LINK.sub(' ', body)
    body_for_tags = MD_LINK.sub(' ', body_for_tags)
    inline = [m.group(1) for m in INLINE_TAG.finditer(body_for_tags)]
    if inline:
        merged = tags + [t for t in inline if t not in tags]
        tags = list(dict.fromkeys(merged))

    return (fm if fm else {}, tags, aliases, body)
