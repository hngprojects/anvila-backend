from typing import Any

import yaml


def build_install_prompt(
    slug: str,
    metadata: dict[str, Any],
    *,
    source_url: str = "",
) -> str:
    """Return a ClawHub-style install prompt string.

    This is stored in Skill.content.
    """
    name = _name(slug, metadata)
    author = _author(slug, metadata)
    page = source_url or _page(slug, metadata)
    description = _description(metadata)
    version = _version(metadata)
    tags = _tags(metadata)

    author_part = f" ({author})" if author else ""
    version_part = f" version {version}" if version else ""

    lines: list[str] = [
        "Before installing anything, inspect the skill metadata and setup requirements.",
        "If this skill asks you to install a third-party package or CLI, verify its source,",
        "maintainer, and package contents before running any install command.",
        "",
        f'Install the skill "{name}"{author_part} from ClawHub{version_part}'
        "only after those checks pass.",
    ]

    if page:
        lines.append(f"Skill page: {page}")

    lines.append("")

    if description:
        lines.append(f"About this skill: {description}")
        lines.append("")

    if tags:
        lines.append(f"Tags: {tags}")
        lines.append("")

    lines += [
        "Keep the work scoped to this skill only.",
        "After install, help finish setup from verified skill metadata.",
        (
            "Use only the metadata you can verify from the skill page; "
            "do not invent missing requirements."
        ),
        "Ask before making any broader environment changes.",
    ]

    return "\n".join(lines)


def build_skill_md(
    slug: str,
    metadata: dict[str, Any],
    *,
    source_url: str = "",
) -> str:
    """Return the full SKILL.md file content including YAML frontmatter.

    This is what gets written to <slug>/SKILL.md in the GitHub repo.
    """
    name = _name(slug, metadata)
    description = _description(metadata) or f"Install and use the {name} skill."
    prompt = build_install_prompt(slug, metadata, source_url=source_url)
    frontmatter = f"---\nname: {_yaml(name)}\ndescription: {_yaml(description)}\n---\n\n"
    return frontmatter + prompt


def _name(slug: str, metadata: dict[str, Any]) -> str:
    name = metadata.get("displayName") or metadata.get("name") or ""
    return str(name).strip() or slug.split("/")[-1].replace("-", " ").title()


def _author(slug: str, metadata: dict[str, Any]) -> str:
    owner = metadata.get("owner") or {}
    handle = (
        owner.get("displayName")
        or owner.get("handle")
        or metadata.get("ownerHandle")
        or metadata.get("handle")
        or ""
    )
    if not handle and "/" in slug:
        handle = slug.split("/")[0]
    return str(handle).strip()


def _page(slug: str, metadata: dict[str, Any]) -> str:
    url = metadata.get("url") or metadata.get("skillPage") or ""
    if url:
        return str(url).strip()
    owner_handle = (metadata.get("owner") or {}).get("handle") or metadata.get("ownerHandle") or ""
    if owner_handle:
        leaf = slug.split("/")[-1]
        return f"https://clawhub.ai/{owner_handle}/{leaf}"
    return f"https://clawhub.ai/{slug.strip('/')}"


def _description(metadata: dict[str, Any]) -> str:
    desc = metadata.get("summary") or metadata.get("description") or ""
    return str(desc).strip()


def _version(metadata: dict[str, Any]) -> str:
    v = metadata.get("latestVersion") or metadata.get("version") or ""
    return str(v).strip()


def _tags(metadata: dict[str, Any]) -> str:
    tags = metadata.get("tags") or []
    if isinstance(tags, list):
        return ", ".join(str(t) for t in tags if t)
    return ""


def _yaml(value: str) -> str:
    dumped = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True)
    return dumped.rstrip("\n")
