# utils.py
import re
from dataclasses import dataclass

# Fenced blocks (```lang … ``` or ~~~)
FENCED_RE = re.compile(
    r'''
    (?P<fence>^(\s*)(`{3,}|~{3,}))[^\n]*\n   # opening fence line (with optional lang)
    (?P<body>.*?)
    ^\2\3\s*$                               # closing fence (same backticks/tilde count)
    ''',
    re.MULTILINE | re.DOTALL | re.VERBOSE
)

# Inline code `...` (greedy-protected; supports multiple backticks)
INLINE_CODE_RE = re.compile(r'(?<!`)`{1,}([^`]|`(?!`))+?`{1,}')

@dataclass
class Masked:
    text: str
    slots: list[str]

class CodeMasker:
    """Masks fenced and inline code regions to protect them from parsing/mutations."""

    TOKEN = "\uE000CODEMASK\uE000"  # private-use area marker

    @classmethod
    def mask(cls, s: str) -> Masked:
        slots: list[str] = []

        # 1) mask fenced blocks first (multiline)
        def repl_fenced(m):
            slots.append(m.group(0))
            return cls.TOKEN + str(len(slots)-1)

        s = FENCED_RE.sub(repl_fenced, s)

        # 2) mask inline code on the remaining text
        def repl_inline(m):
            slots.append(m.group(0))
            return cls.TOKEN + str(len(slots)-1)

        s = INLINE_CODE_RE.sub(repl_inline, s)

        return Masked(text=s, slots=slots)

    @classmethod
    def unmask(cls, masked: Masked) -> str:
        s = masked.text

        # Replace tokens back in reverse to avoid partial overlaps
        for idx in range(len(masked.slots) - 1, -1, -1):
            s = s.replace(cls.TOKEN + str(idx), masked.slots[idx])
        return s
