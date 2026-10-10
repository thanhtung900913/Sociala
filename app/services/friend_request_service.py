from uuid import UUID

from app.db.connection import get_db_connection_context
from app.models.friend_request_model import (
    RespondFriendRequestBody, SendFriendRequestBody, FriendRequestsCursor,
    FriendRequestResponseBody, FriendRequestsQuery, FriendRequestsResponseBody,
)
from app.services import user_service
from app.services.errors import ServiceError
from app.utils.pagination import decode_cursor, encode_cursor


def _fail(code, message, status):
    raise ServiceError({"error": code, "message": message}, status)


def lock_relationship_pair(cur, actor_id, peer_id):
    """Lock a canonical pair, including pairs without a friendship row.

    Other friend/block writers must acquire this same transaction-scoped lock
    before reading or changing the pair.
    """
    actor_id, peer_id = str(UUID(str(actor_id))), str(UUID(str(peer_id)))
    if actor_id == peer_id:
        _fail(
            "SELF_RELATION_NOT_ALLOWED",
            "Cannot create a relationship with yourself", 422,
        )
    low_id, high_id = sorted((actor_id, peer_id))
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%(pair_key)s, 0))",
        {"pair_key": f"relationship:{low_id}:{high_id}"},
    )
    return {
        "actor_id": actor_id, "peer_id": peer_id,
        "low_id": low_id, "high_id": high_id,
    }


def _load_pair(cur, actor_id, peer_id):
    params = lock_relationship_pair(cur, actor_id, peer_id)
    # Prevent account deletion/status changes until the mutation commits.
    cur.execute(
        """
        SELECT u.id, u.username, u.status, u.deleted_at,
               COALESCE(p.display_name, u.username) AS display_name,
               to_jsonb(avatar) AS avatar
        FROM public.users u
        LEFT JOIN public.user_profiles p ON p.user_id = u.id
        LEFT JOIN public.media_assets avatar ON avatar.id = p.avatar_media_id
        WHERE u.id IN (%(actor_id)s::uuid, %(peer_id)s::uuid)
        ORDER BY u.id
        FOR SHARE OF u
        """,
        params,
    )
    users = {str(row["id"]): row for row in cur.fetchall()}
    actor = users.get(params["actor_id"])
    if (
        actor is None or actor["status"] != "ACTIVE"
        or actor["deleted_at"] is not None
    ):
        _fail("FORBIDDEN", "Current user is not active", 403)
    peer = users.get(params["peer_id"])
    if (
        peer is None or peer["status"] != "ACTIVE"
        or peer["deleted_at"] is not None
    ):
        _fail("NOT_FOUND", "User is unavailable", 404)
    cur.execute(
        """
        SELECT 1 FROM public.user_blocks b
        WHERE (b.blocker_id = %(actor_id)s AND b.blocked_id = %(peer_id)s)
           OR (b.blocker_id = %(peer_id)s AND b.blocked_id = %(actor_id)s)
        LIMIT 1
        """,
        params,
    )
    if cur.fetchone() is not None:
        _fail("NOT_FOUND", "User is unavailable", 404)
    cur.execute(
        """
        SELECT user_low_id, user_high_id, requested_by_id, status,
               requested_at, responded_at, updated_at
        FROM public.friendships
        WHERE user_low_id = %(low_id)s AND user_high_id = %(high_id)s
        FOR UPDATE
        """,
        params,
    )
    return params, peer, cur.fetchone()


def _build_relationship(row, peer) -> dict:
    requester_id = str(row["requested_by_id"])
    low_id, high_id = str(row["user_low_id"]), str(row["user_high_id"])
    return {
        "peer": user_service.build_user_summary(peer),
        "requester_id": requester_id,
        "recipient_id": high_id if requester_id == low_id else low_id,
        "status": row["status"], "requested_at": row["requested_at"],
        "responded_at": row["responded_at"], "updated_at": row["updated_at"],
    }


def send_friend_request(
    actor_id, body: SendFriendRequestBody
) -> tuple[FriendRequestResponseBody, bool]:
    """Create/reset an attempt, or return the sender's pending request."""
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            params, peer, row = _load_pair(cur, actor_id, body.user_id)
            created = True
            if row is not None and row["status"] == "ACCEPTED":
                _fail("ALREADY_FRIENDS", "Users are already friends", 409)
            if row is not None and row["status"] == "PENDING":
                if str(row["requested_by_id"]) != params["actor_id"]:
                    _fail(
                        "INCOMING_REQUEST_EXISTS",
                        "An incoming request already exists", 409,
                    )
                created = False
            elif row is None:
                cur.execute(
                    """
                    INSERT INTO public.friendships
                        (user_low_id, user_high_id, requested_by_id)
                    VALUES (%(low_id)s, %(high_id)s, %(actor_id)s)
                    RETURNING *
                    """,
                    params,
                )
                row = cur.fetchone()
            else:
                cur.execute(
                    """
                    UPDATE public.friendships
                    SET requested_by_id = %(actor_id)s, status = 'PENDING',
                        requested_at = GREATEST(
                            clock_timestamp(),
                            requested_at + INTERVAL '1 microsecond'
                        ),
                        responded_at = NULL
                    WHERE user_low_id = %(low_id)s
                      AND user_high_id = %(high_id)s
                    RETURNING *
                    """,
                    params,
                )
                row = cur.fetchone()
            result = _build_relationship(row, peer)
        conn.commit()
    return FriendRequestResponseBody.model_validate(result), created


def _check_attempt(row, requested_at):
    if row["requested_at"] != requested_at:
        _fail(
            "REQUEST_CHANGED",
            "The current request has a different timestamp", 409,
        )


def _respond_to_request(
    actor_id, peer_id, body: RespondFriendRequestBody, target_status
) -> FriendRequestResponseBody:
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            params, peer, row = _load_pair(cur, actor_id, peer_id)
            if row is None:
                _fail("NOT_FOUND", "Friend request not found", 404)
            _check_attempt(row, body.requested_at)
            if str(row["requested_by_id"]) == params["actor_id"]:
                _fail(
                    "NOT_REQUEST_RECIPIENT",
                    "Only the recipient can respond", 403,
                )
            if row["status"] not in ("PENDING", target_status):
                _fail(
                    "INVALID_RELATIONSHIP_STATE",
                    "Cannot respond to this request state", 409,
                )
            if row["status"] == "PENDING":
                cur.execute(
                    """
                    UPDATE public.friendships
                    SET status = %(status)s, responded_at = clock_timestamp()
                    WHERE user_low_id = %(low_id)s
                      AND user_high_id = %(high_id)s
                    RETURNING *
                    """,
                    {**params, "status": target_status},
                )
                row = cur.fetchone()
            result = _build_relationship(row, peer)
        conn.commit()
    return FriendRequestResponseBody.model_validate(result)


def accept_friend_request(
    actor_id, peer_id, body: RespondFriendRequestBody
) -> FriendRequestResponseBody:
    return _respond_to_request(actor_id, peer_id, body, "ACCEPTED")


def reject_friend_request(
    actor_id, peer_id, body: RespondFriendRequestBody
) -> FriendRequestResponseBody:
    return _respond_to_request(actor_id, peer_id, body, "REJECTED")


def cancel_friend_request(
    actor_id, peer_id, query: RespondFriendRequestBody
) -> None:
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            params, _, row = _load_pair(cur, actor_id, peer_id)
            if row is not None:
                _check_attempt(row, query.requested_at)
                if str(row["requested_by_id"]) != params["actor_id"]:
                    _fail(
                        "NOT_REQUEST_SENDER", "Only the sender can cancel", 403
                    )
                if row["status"] == "ACCEPTED":
                    _fail(
                        "ALREADY_FRIENDS",
                        "Use the unfriend endpoint instead", 409,
                    )
                if row["status"] == "PENDING":
                    cur.execute(
                        """
                        UPDATE public.friendships
                        SET status = 'CANCELLED',
                            responded_at = clock_timestamp()
                        WHERE user_low_id = %(low_id)s
                          AND user_high_id = %(high_id)s
                        """,
                        params,
                    )
        conn.commit()


def list_friend_requests(
    actor_id, query: FriendRequestsQuery
) -> FriendRequestsResponseBody:
    filters = {"direction": query.direction}
    position = decode_cursor(
        query.cursor, "friend-requests", actor_id, filters,
        FriendRequestsCursor,
    )
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            cur.execute(
                """
                SELECT id FROM public.users
                WHERE id = %(actor_id)s AND status = 'ACTIVE'
                  AND deleted_at IS NULL
                """,
                {"actor_id": actor_id},
            )
            if cur.fetchone() is None:
                _fail("FORBIDDEN", "Current user is not active", 403)
            cur.execute(
                """
                SELECT f.user_low_id, f.user_high_id, f.requested_by_id,
                       f.status,
                       f.requested_at, f.responded_at, f.updated_at,
                       u.id, u.username,
                       COALESCE(p.display_name, u.username) AS display_name,
                       to_jsonb(avatar) AS avatar
                FROM public.friendships f
                JOIN public.users u ON u.id = CASE
                    WHEN f.user_low_id = %(actor_id)s::uuid THEN f.user_high_id
                    ELSE f.user_low_id END
                LEFT JOIN public.user_profiles p ON p.user_id = u.id
                LEFT JOIN public.media_assets avatar
                  ON avatar.id = p.avatar_media_id
                WHERE %(actor_id)s::uuid IN (f.user_low_id, f.user_high_id)
                  AND f.status = 'PENDING'
                  AND ((%(direction)s = 'incoming'
                        AND f.requested_by_id <> %(actor_id)s)
                    OR (%(direction)s = 'outgoing'
                        AND f.requested_by_id = %(actor_id)s))
                  AND u.status = 'ACTIVE' AND u.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM public.user_blocks b
                      WHERE (b.blocker_id = %(actor_id)s
                             AND b.blocked_id = u.id)
                         OR (b.blocker_id = u.id
                             AND b.blocked_id = %(actor_id)s)
                  )
                  AND (%(cursor_time)s::timestamptz IS NULL
                    OR (f.requested_at, u.id) <
                       (%(cursor_time)s::timestamptz, %(cursor_id)s::uuid))
                ORDER BY f.requested_at DESC, u.id DESC
                LIMIT %(limit)s
                """,
                {
                    "actor_id": actor_id, "direction": query.direction,
                    "cursor_time": position.requested_at if position else None,
                    "cursor_id": str(position.id) if position else None,
                    "limit": query.limit + 1,
                },
            )
            rows = cur.fetchall()
        conn.commit()
    has_more = len(rows) > query.limit
    rows = rows[:query.limit]
    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = encode_cursor(
            "friend-requests", actor_id, filters,
            {
                "requested_at": last["requested_at"].isoformat(),
                "id": str(last["id"]),
            },
        )
    return FriendRequestsResponseBody.model_validate({
        "data": [_build_relationship(row, row) for row in rows],
        "pagination": {
            "limit": query.limit, "has_more": has_more,
            "next_cursor": next_cursor,
        },
    })
