"""Game name normalization utilities."""
import re
import unicodedata

ARTICLE_PATTERN_BEGIN = re.compile(r"^\b(|a|an|the|le|la|l'|un|une|el|los|las|de|der|die|das)\b")
ARTICLE_PATTERN_END = re.compile(r",\s?(the|a|an|le|la|l'|un|une|el|los|las|de|der|die|das)(?=\s|$|:)")

def remove_parentheses(text):
    """Remove text between parentheses including the parentheses"""
    return re.sub(r'\s*\([^()]*(?:\([^()]*\)[^()]*)*\)', '', text).strip()

def remove_brackets(text):
    """Remove text between square brackets including the brackets"""
    return re.sub(r'\s*\[[^\[\]]*\]', '', text).strip()

def romain_vers_arabe_1_9(texte: str) -> str:
    """Convert Roman numerals I-IX to Arabic numerals 1-9"""
    mapping = {
        "I": "1",
        "II": "2",
        "III": "3",
        "IV": "4",
        "V": "5",
        "VI": "6",
        "VII": "7",
        "VIII": "8",
        "IX": "9"
    }

    # Match Roman numerals I-IX, excluding when part of abbreviations
    pattern = r'(?<![A-Za-z.])(?:IX|VIII|VII|VI|V|IV|III|II|(?!\.)I(?!\.))(?=\b|_)(?![A-Za-z.])'

    def remplacement(match):
        romain = match.group(0).upper()
        return mapping[romain]

    return re.sub(pattern, remplacement, texte, flags=re.IGNORECASE)

def normalize_game_name(name, remove_paranthesis=True, remove_articles=True):
    """Normalize game name for consistent matching across the application"""
    if not name:
        return ""

    # Normalize accented characters to their base forms
    normalized = unicodedata.normalize('NFD', name)
    name = "".join(c for c in normalized if not unicodedata.combining(c))

    # Remove parentheses first (before moving articles)
    if remove_paranthesis:
        name = remove_parentheses(name)
        
    name = remove_brackets(name)
    
    # When remove_articles=False, convert trailing articles (after comma) to beginning
    if not remove_articles:
        patterns = [
            (r',\s*The\s*(?:$|[-:])', 'The'),
            (r',\s*La\s*(?:$|[-:])', 'La'),
            (r',\s*Le\s*(?:$|[-:])', 'Le'),
            (r",\s*L'\s*(?:$|[-:])", "L'"),
            (r',\s*Der\s*(?:$|[-:])', 'Der'),
            (r',\s*Die\s*(?:$|[-:])', 'Die'),
            (r',\s*Das\s*(?:$|[-:])', 'Das'),
            (r',\s*A\s*(?:$|[-:])', 'A'),
        ]
        
        for pattern, article in patterns:
            matched = re.search(pattern, name, flags=re.IGNORECASE)
            if matched:
                name = re.sub(pattern, '', name, flags=re.IGNORECASE)
                name = re.sub(r'\s*[-:]\s*', ' ', name).strip()
                if article == "L'":
                    name = f"{article}{name.strip()}"
                else:
                    name = f"{article} {name.strip()}"
                break
    
    normalized = name

    # Remove roman numerals and convert to numbers
    normalized = romain_vers_arabe_1_9(normalized).lower()

    # Remove standalone "1" (but not when part of larger numbers like 1,000)
    normalized = re.sub(r"\b1\b(?!,\d)", "", normalized)

    # Remove articles (the, a, an, le, etc.)
    if remove_articles:
        normalized = ARTICLE_PATTERN_BEGIN.sub("", normalized)
        normalized = ARTICLE_PATTERN_END.sub("", normalized)    

    normalized = normalized.replace("&", "and")
    
    # Keep only ASCII letters, numbers, and parentheses
    normalized = re.sub(r'[^a-zA-Z0-9()]', '', normalized)

    return normalized




