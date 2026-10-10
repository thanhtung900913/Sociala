from uuid import UUID

from app.services.errors import ServiceError


def lock_relationship_pair(cur, actor_id, peer_id):
    """Serialize friend/block/restriction mutations for a canonical pair."""
    actor_id, peer_id = str(UUID(str(actor_id))), str(UUID(str(peer_id)))
    if actor_id == peer_id:
        raise ServiceError({
            "error": "SELF_RELATION_NOT_ALLOWED",
            "message": "Cannot create a relationship with yourself",
        }, 422)
    low_id, high_id = sorted((actor_id, peer_id))
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%(pair_key)s, 0))",
        {"pair_key": f"relationship:{low_id}:{high_id}"},
    )
    return {
        "actor_id": actor_id, "peer_id": peer_id,
        "low_id": low_id, "high_id": high_id,
    }
