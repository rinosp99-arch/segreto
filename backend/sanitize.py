import re

# Minimal HTML sanitizer for editorial content coming from admin / external webhook.
# NOTE: This is a pragmatic allowlist sanitizer. For production, replace with a
# vetted library (e.g. bleach / nh3) before going live.

_ALLOWED_TAGS = {
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'h2', 'h3', 'h4', 'ul', 'ol', 'li',
    'blockquote', 'a', 'img', 'figure', 'figcaption', 'hr', 'span'
}

_SCRIPT_STYLE = re.compile(r'<(script|style|iframe|object|embed|form)[^>]*>.*?</\1>', re.IGNORECASE | re.DOTALL)
_SELF_DANGEROUS = re.compile(r'<(script|style|iframe|object|embed|form|link|meta)[^>]*/?>', re.IGNORECASE)
_ON_ATTR = re.compile(r'\son\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE)
_JS_HREF = re.compile(r'(href|src)\s*=\s*(["\"])\s*javascript:[^"\"]*\2', re.IGNORECASE)


def sanitize_html(html: str) -> str:
    if not html:
        return ''
    cleaned = _SCRIPT_STYLE.sub('', html)
    cleaned = _SELF_DANGEROUS.sub('', cleaned)
    cleaned = _ON_ATTR.sub('', cleaned)
    cleaned = _JS_HREF.sub('', cleaned)
    return cleaned.strip()


def slugify(text: str) -> str:
    text = (text or '').lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-') or 'senza-nome'
