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
