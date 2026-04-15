import re
from typing import List

# ---------------------------------------------------------------------------
# Drop-cap recombinator
# Matches patterns like: <span>W</span>Quando  →  <span>Q</span>uando
# Works for any single HTML tag wrapping exactly one letter, followed
# immediately (no space) by a word whose first letter is *different* from the
# trapped one (because the LLM translated the word but kept the original letter).
# ---------------------------------------------------------------------------
_DROP_CAP_RE = re.compile(
    r'(<(?P<tag>[a-zA-Z][^>]*)>)'   # opening tag
    r'[A-Za-zÀ-ÿ]'                  # single original (now orphaned) letter
    r'(</[a-zA-Z]+>)'               # closing tag
    r'\s*'                           # optional whitespace between tag and word
    r'(?P<word>[A-ZÀ-Ÿ][A-Za-zÀ-ÿ]+)',  # translated word starting with uppercase
)

def _fix_drop_cap(m: re.Match) -> str:
    word = m.group("word")
    open_tag = m.group(1)
    close_tag = m.group(3)
    return f"{open_tag}{word[0]}{close_tag}{word[1:]}"


def _postprocess(text: str) -> str:
    """Apply formatting fixes to a translated text block."""
    # 1. Fix drop-cap artefacts (e.g. <span>W</span>Quando → <span>Q</span>uando)
    text = _DROP_CAP_RE.sub(_fix_drop_cap, text)
    # 2. Ensure space after em-dash when followed directly by a letter
    text = re.sub(r'—(?=[A-Za-zÀ-ÿ])', '— ', text)
    # 3. Collapse multiple spaces into one (outside HTML tags content is fine)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text


class DomBatcher:
    """Helper to group multiple BeautifulSoup tags into a single prompt input."""
    def __init__(self, max_chars=1500):
        self.max_chars = max_chars
        self.current_batch = []
        self.current_tags = []
        self.batches = [] # List of tuple (xml_string, list_of_tags)
        self.char_count = 0
        
    def add_tag(self, tag):
        if tag.name == 'img':
            content = tag.get('alt', '').strip()
        else:
            content = tag.decode_contents().strip()
            
        if not content:
            return
            
        self.current_batch.append(content)
        self.current_tags.append(tag)
        self.char_count += len(content)
        
        # O flush ocorre quando passa do limite E acabou de processar um parágrafo.
        # Caso ultrapasse muito o limite (ex: tabelas gigantes), faz flush na mesma para não quebrar o LLM.
        if self.char_count >= self.max_chars:
            if tag.name == 'p' or self.char_count >= self.max_chars + 800:
                self._flush()
            
    def _flush(self):
        if not self.current_batch:
            return
        
        xml_parts = ["<batch>"]
        for i, text in enumerate(self.current_batch):
            xml_parts.append(f'<t id="{i}">{text}</t>')
        xml_parts.append("</batch>")
        
        self.batches.append(("\n".join(xml_parts), self.current_tags))
        self.current_batch = []
        self.current_tags = []
        self.char_count = 0
        
    def finish(self):
        self._flush()
        return self.batches

def parse_translated_batch(translated_xml: str) -> dict:
    """Parses the LLM output XML and returns a mapping of id -> translated text."""
    # LLMs might add markdown blocks like ```xml ... ```
    xml_str = re.sub(r'```[a-z]*\n(.*?)\n```', r'\1', translated_xml, flags=re.DOTALL)
    
    # We aggressively find <t id="x">...</t>
    results = {}
    pattern = re.compile(r'<t\s+id=["\'"]?(\d+)["\'"]?>(.*?)</t>', re.DOTALL)
    matches = pattern.findall(xml_str)
    for t_id, t_content in matches:
        results[int(t_id)] = _postprocess(t_content.strip())
    return results
