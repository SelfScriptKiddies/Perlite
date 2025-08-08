from .utils import CodeMasker

def extract_inline_tags(body: str, tag_re) -> list[str]:
    # Mask code regions so hashtags in code are ignored
    masked = CodeMasker.mask(body)
    tags = [m.group(1) for m in tag_re.finditer(masked.text)]
    return tags
