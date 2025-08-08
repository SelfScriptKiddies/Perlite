"""
Link resolution & normalization:
- Note links become root-relative shortest (vault mode) or true relative (relative mode)
- Attachment links become relative-to-current-file (always)
- Build/maintain basename index per vault
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

MD_LINK   = re.compile(r'(!?)\[(?P<text>[^\]]*)\]\((?P<url>[^)]+)\)')
WIKI_LINK = re.compile(r'(?P<bang>!?)\[\[(?P<body>.+?)\]\]')

MD_EXTS  = {".md", ".markdown", ".mdown"}
IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf"}
ASSET_EXTS = IMG_EXTS | {".mp4", ".m4a", ".webm", ".mov", ".mp3", ".wav", ".ogg"}

def is_md(p: Path) -> bool:
    return p.suffix.lower() in MD_EXTS

def strip_md_ext(path_str: str) -> str:
    p = Path(path_str)
    if p.suffix.lower() in MD_EXTS:
        return p.with_suffix("").as_posix()
    return p.as_posix()

def to_rel(base: Path, abs_file: Path) -> str:
    return os.path.relpath(abs_file, start=base).replace("\\", "/")

class Resolver:
    def __init__(self, root: Path, shortest_mode: str = "vault"):
        self.ROOT = root.resolve()
        self.mode = shortest_mode  # "vault" or "relative"
        # Index all markdown files for basename/stem lookup
        self.ALL_MD: List[Path] = sorted([p for p in self.ROOT.rglob("*") if p.is_file() and is_md(p)])
        self.BASENAME_INDEX: Dict[str, List[Path]] = {}
        for p in self.ALL_MD:
            self.BASENAME_INDEX.setdefault(p.name, []).append(p)
            self.BASENAME_INDEX.setdefault(p.stem, []).append(p)

    # ----- utilities bound to this vault -----

    def rel_from_root(self, path: Path) -> str:
        return path.relative_to(self.ROOT).as_posix()

    def _collect_conflicts(self, stem_or_name: str) -> List[Path]:
        return list(dict.fromkeys(
            self.BASENAME_INDEX.get(stem_or_name, []) +
            self.BASENAME_INDEX.get(Path(stem_or_name).stem, [])
        ))

    # ----- core resolution -----

    def find_target_path(self, current_file: Path, raw: str) -> str:
        """Resolve note target to vault-rooted path (no .md). Keep #anchor if present."""
        anchor = None
        if "#" in raw:
            raw, anchor = raw.split("#", 1)

        raw = raw.strip()
        if raw == "":
            return "#" + anchor if anchor else ""

        candidate = Path(raw)
        if candidate.is_absolute():
            candidate = Path(str(candidate).lstrip("/"))

        base = current_file.parent
        abs_path = (base / candidate).resolve()
        if abs_path.exists():
            out = strip_md_ext(self.rel_from_root(abs_path))
        else:
            bn = candidate.name
            matches = self.BASENAME_INDEX.get(bn, []) + self.BASENAME_INDEX.get(strip_md_ext(bn), [])
            uniq = list(dict.fromkeys(matches))
            if len(uniq) == 1:
                out = strip_md_ext(self.rel_from_root(uniq[0]))
            else:
                out = strip_md_ext(candidate.as_posix())

        if anchor:
            out += f"#{anchor}"
        return out

    def _shortest_suffix_from_vault(self, target_abs_no_ext: str) -> str:
        """Root-relative shortest, at least 'dir/stem' if not in root."""
        target_path = Path(target_abs_no_ext)
        parts = target_path.parts
        stem = target_path.name

        conflicts = self._collect_conflicts(stem)
        conflict_noext = {strip_md_ext(self.rel_from_root(p)) for p in conflicts}

        def unique(sfx: str) -> bool:
            matches = [c for c in conflict_noext if c.endswith('/' + sfx) or c == sfx]
            return len(matches) == 1 and matches[0] == target_abs_no_ext

        if len(parts) == 1:
            return stem

        candidates = []
        for take in range(2, len(parts) + 1):
            candidates.append(Path(*parts[-take:]).as_posix())
        candidates.sort(key=lambda s: (s.count('/') + 1, len(s)))

        if unique(candidates[0]):
            return candidates[0]
        for c in candidates[1:]:
            if unique(c):
                return c
        return target_abs_no_ext

    def _shortest_relative_from_current(self, current_file: Path, target_abs_no_ext: str) -> str:
        base = current_file.parent
        target = self.ROOT / (target_abs_no_ext + ".md")
        try:
            rel = Path(to_rel(base, target)).with_suffix("")
        except Exception:
            rel = Path(target_abs_no_ext)
        return rel.as_posix()

    def resolve_target_for_text_and_meta(self, current_file: Path, raw: str) -> Tuple[str, str | None]:
        """Return (text_target_no_ext[#anchor], meta_relpath_with_md)."""
        if "|" in raw:
            target, _ = raw.split("|", 1)
        else:
            target = raw

        anchor = None
        if "#" in target:
            target, anchor = target.split("#", 1)

        target = target.strip()
        if not target:
            return (raw, None)

        abs_no_ext = self.find_target_path(current_file, target)
        abs_no_ext_clean = abs_no_ext.split("#", 1)[0]

        if self.mode == "relative":
            shortest = self._shortest_relative_from_current(current_file, abs_no_ext_clean)
        else:
            shortest = self._shortest_suffix_from_vault(abs_no_ext_clean)

        text_target = f"{shortest}#{anchor}" if anchor else shortest
        meta_with_md = abs_no_ext_clean + ".md"
        return (text_target, meta_with_md)

    # ----- attachments -----

    def resolve_asset_for_text(self, current_file: Path, raw: str) -> str:
        """
        Resolve attachment/media by BASENAME across the whole vault and return
        the relative path from the current note folder.

        Rules:
        - Ignore any folders typed in the link; use only the basename.
        - If 'raw' has an extension -> search exactly that basename.
        - If 'raw' has no extension -> try all ASSET_EXTS for that basename.
        - If multiple matches:
            * prefer same directory as the note,
            * then the shortest relative path length,
            * then lexicographic by the relative path.
        - Always emit a POSIX relative path; if it points into a subdir,
        prefix with "./" (Perlite-friendly).
        """
        # strip alias and keep only basename (drop folders typed by the user)
        target = raw.split("|", 1)[0].strip()
        if not target:
            return raw

        base = current_file.parent
        name = Path(target).name  # basename only

        # Collect candidates in the whole vault
        candidates: list[Path] = []
        if "." in name:  # has extension -> exact basename search
            for f in self.ROOT.rglob(name):
                if f.is_file():
                    candidates.append(f)
        else:
            # no extension -> try known asset extensions
            for ext in ASSET_EXTS:
                for f in self.ROOT.rglob(name + ext):
                    if f.is_file():
                        candidates.append(f)

        if not candidates:
            # nothing found; keep as typed (basename)
            return name

        # Ranking:
        #  1) same directory as the note (best)
        #  2) shortest relative path length (closest)
        #  3) lexicographic tie-break by the relative path
        def rank(p: Path):
            same_dir = 0 if p.parent.resolve() == base.resolve() else 1
            rel = to_rel(base, p)
            return (same_dir, len(rel), rel)

        candidates.sort(key=rank)
        best = candidates[0]
        rel = to_rel(base, best)

        # Prefix "./" if it's a subdir (not already ./ or ../ and not absolute)
        if not rel.startswith(("./", "../")) and "/" in rel and not rel.startswith("/"):
            rel = "./" + rel
        return rel


    # ----- normalization passes -----

    def normalize_md_links_to_wikilinks(self, current_file: Path, text: str) -> str:
        """Convert standard Markdown links to wikilinks where appropriate."""
        def repl(m):
            bang = m.group(1)
            url  = m.group("url").strip()

            if url.startswith("#"):
                return m.group(0)

            if re.match(r'^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)', url):
                return m.group(0)

            target = self.find_target_path(current_file, url)

            suffix = Path(url).suffix.lower()
            if bang == "!" or suffix in IMG_EXTS or suffix in ASSET_EXTS:
                asset_rel = self.resolve_asset_for_text(current_file, url)
                return f"![[{asset_rel}]]"

            return f"[[{target}]]"

        return MD_LINK.sub(repl, text)

    def normalize_wikilinks_in_text(self, current_file: Path, text: str) -> str:
        """Normalize wikilinks [[...]] and ![[...]] preserving alias and #anchor."""
        def repl(m):
            bang  = m.group("bang")
            body  = m.group("body")
            alias = None
            if "|" in body:
                target_part, alias = body.split("|", 1)
            else:
                target_part = body

            if bang == "!":
                asset_rel = self.resolve_asset_for_text(current_file, target_part)
                return f"![[{asset_rel}|{alias}]]" if alias is not None else f"![[{asset_rel}]]"

            text_target, _meta = self.resolve_target_for_text_and_meta(current_file, body)
            if not text_target or text_target.strip() == body.strip():
                return m.group(0)
            return f"[[{text_target}|{alias}]]" if alias is not None else f"[[{text_target}]]"
        return WIKI_LINK.sub(repl, text)
