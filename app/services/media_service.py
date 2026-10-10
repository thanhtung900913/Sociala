def visible_media(media, owner_id) -> dict | None:
    """Select public fields from owned, ready and undeleted media."""
    if (
        not media
        or media.get("status") != "READY"
        or media.get("deleted_at")
        or str(media.get("owner_id")) != str(owner_id)
    ):
        return None
    # Download URLs remain unavailable until media delivery is wired.
    result = {
        name: media.get(name)
        for name in (
            "id", "content_type", "byte_size", "width", "height", "status",
            "created_at",
        )
    }
    return {**result, "download_url": None, "url_expires_at": None}
