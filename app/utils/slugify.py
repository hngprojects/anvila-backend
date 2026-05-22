import re


def slugify(name: str) -> str:
    """Convert a persona name to a valid GitHub repo slug."""
    name = name.strip().lower()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")
