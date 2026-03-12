import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlparse


def normalize(text: str) -> str:
    """Strip accents/diacritics so Mondelēz matches Mondelez, etc."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


@dataclass
class BrandMention:
    brand: str
    mentioned: bool
    rank: int | None  # 1-based position among tracked brands, None if not mentioned
    sources: list[str] = field(default_factory=list)
    citation_type: str = "none"  # 'official', 'other', 'none'


# Official domains for brands
OFFICIAL_DOMAINS = {
    "mondelez": ["mondelezinternational.com", "mondelez.com"],
    "nestlé": ["nestle.com", "nestle.vn", "nestle.com.vn"],
    "nestle": ["nestle.com", "nestle.vn", "nestle.com.vn"],
    "mars": ["mars.com", "mars.com.vn", "marsinc.com"],
    "pepsico": ["pepsico.com", "pepsico.com.vn"],
    "orion": ["orionworld.com", "oriongroup.com.vn"],
    "ferrero": ["ferrero.com"],
}


def get_citation_type(brand: str, sources: list[str]) -> str:
    """
    Determine citation type based on sources

    Returns:
        'official': Official brand website cited
        'other': Other websites cited
        'none': No citations
    """
    if not sources:
        return "none"

    brand_lower = brand.lower()
    official_domains = OFFICIAL_DOMAINS.get(brand_lower, [])

    # Check if any source is official
    for source in sources:
        source_lower = source.lower()
        for official in official_domains:
            if official in source_lower:
                return "official"

    # Has sources but not official
    return "other"


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from text."""
    url_pattern = re.compile(r'https?://[^\s\)\]\>\"\']+')
    return url_pattern.findall(text)


def extract_domains(urls: list[str]) -> list[str]:
    """Extract unique domains from URLs."""
    domains = set()
    for url in urls:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain:
                domains.add(domain)
        except Exception:
            continue
    return sorted(domains)


def find_nearby_sources(text: str, brand: str, all_urls: list[str], window: int = 500) -> list[str]:
    """Find URLs that appear near a brand mention."""
    text_norm = normalize(text).lower()
    brand_norm = normalize(brand).lower()
    idx = text_norm.find(brand_norm)
    if idx == -1:
        return []

    # Get text window around the brand mention
    start = max(0, idx - window)
    end = min(len(text), idx + len(brand) + window)
    context = text[start:end]

    nearby_urls = extract_urls(context)
    return extract_domains(nearby_urls)


def find_list_rank(text: str, brand: str) -> int | None:
    """
    Find the rank of a brand in a numbered/bulleted list within the response.

    Detects patterns like:
      1. Mondelez  /  1) Mondelez  /  **1. Mondelez**  /  - Mondelez (first item)
    Returns the list number (1-based), or None if not in a list.
    """
    text_norm = normalize(text)
    brand_norm = normalize(brand)

    # Try numbered list: "1. Brand", "1) Brand", "**1. Brand**", "### 1. Brand", "### 1. 🥇 Brand"
    pattern = re.compile(
        r'(?:^|\n)\s*(?:#{1,6}\s+)?(?:\*{0,2})(\d+)[.)]\s*\*{0,2}\s*[^\n]*?' + re.escape(brand_norm),
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text_norm)
    if match:
        return int(match.group(1))

    # Try bullet list: count position among "- " or "* " or "• " items
    brand_lower = brand_norm.lower()
    bullet_pattern = re.compile(r'(?:^|\n)\s*[-•]\s+(.+)', re.MULTILINE)
    for idx, m in enumerate(bullet_pattern.finditer(text_norm), start=1):
        line = re.sub(r'\*{1,2}', '', m.group(1)).lower()
        if brand_lower in line:
            return idx

    # Try markdown table rows: | Brand | ... |
    table_pattern = re.compile(r'(?:^|\n)\|(.+)\|', re.MULTILINE)
    data_rows = []
    for m in table_pattern.finditer(text_norm):
        row = m.group(1)
        # Skip header separator rows (|---|---|)
        if re.match(r'\s*[-:|\s]+$', row):
            continue
        data_rows.append(row)
    for idx, row in enumerate(data_rows, start=1):
        row_clean = re.sub(r'\*{1,2}', '', row).lower()
        if brand_lower in row_clean:
            return idx

    # Try markdown heading sections: ### 🇺🇸 **Oreo** ... Mondelez in description
    heading_pattern = re.compile(r'(?:^|\n)#{1,6}\s+(.+?)(?:\n|$)', re.MULTILINE)
    headings = list(heading_pattern.finditer(text_norm))
    for idx, m in enumerate(headings):
        # Check the section between this heading and the next
        start = m.end()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(text_norm)
        section = text_norm[start:end]
        heading_text = re.sub(r'\*{1,2}', '', m.group(1)).lower()
        if brand_lower in heading_text or brand_lower in section.lower():
            return idx + 1

    return None


def extract_brands(
    response_text: str,
    brands: list[str],
    extra_citations: list[str] | None = None,
) -> list[BrandMention]:
    """
    Extract brand mentions, rankings, and sources from AI response text.

    Args:
        response_text: Full text response from AI engine.
        brands: List of brand names to track.
        extra_citations: Additional citation URLs (e.g., from Perplexity API).

    Returns:
        List of BrandMention for each tracked brand.
    """
    text_norm = normalize(response_text)
    all_urls = extract_urls(response_text)
    if extra_citations:
        all_urls.extend(extra_citations)

    results = []
    for brand in brands:
        # Check if brand is mentioned (accent-insensitive)
        pattern = re.compile(re.escape(normalize(brand)), re.IGNORECASE)
        match = pattern.search(text_norm)

        if match:
            # Find rank in numbered/bulleted list
            rank = find_list_rank(response_text, brand)

            sources = find_nearby_sources(response_text, brand, all_urls)
            if extra_citations:
                sources = list(set(sources) | set(extract_domains(extra_citations)))

            citation_type = get_citation_type(brand, sources)

            results.append(BrandMention(
                brand=brand,
                mentioned=True,
                rank=rank,
                sources=sources,
                citation_type=citation_type,
            ))
        else:
            results.append(BrandMention(
                brand=brand,
                mentioned=False,
                rank=None,
                sources=[],
            ))

    return results
