def build_box(title: str, body: str) -> str:
    sep = "━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return "\n".join([sep, title, sep, "", body, "", sep])


def truncate_discord(content: str, limit: int = 2000) -> str:
    content = str(content or "")
    if len(content) <= int(limit):
        return content
    suffix = "...(truncated)"
    keep = int(limit) - len(suffix)
    if keep <= 0:
        return suffix[: int(limit)]
    return content[:keep] + suffix


def buildEmbed(
    *,
    title: str,
    description: str | None,
    color: int,
    fields: list[dict] | None,
    footer: str | None,
    timestamp: str | None,
) -> dict:
    embed: dict = {"title": str(title or ""), "color": int(color)}

    if description is not None:
        desc = str(description)
        if len(desc) > 1000:
            desc = desc[:997] + "..."
        if desc.strip():
            embed["description"] = desc

    normalized_fields: list[dict] = []
    if fields:
        for f in fields:
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or "").strip()
            value = str(f.get("value") or "").strip()
            if not name or not value:
                continue
            if len(name) > 256:
                name = name[:253] + "..."
            if len(value) > 1024:
                value = value[:1021] + "..."
            inline = bool(f.get("inline", False))
            normalized_fields.append({"name": name, "value": value, "inline": inline})
            if len(normalized_fields) >= 25:
                break

    if normalized_fields:
        embed["fields"] = normalized_fields

    if footer is not None:
        ft = str(footer).strip()
        if ft:
            if len(ft) > 2048:
                ft = ft[:2045] + "..."
            embed["footer"] = {"text": ft}

    if timestamp is not None:
        ts = str(timestamp).strip()
        if ts:
            embed["timestamp"] = ts

    return embed
