"""Read authoritative posts and resolve recipients allowed to view them."""

from contextlib import contextmanager
from pathlib import Path


AUTHOR_SQL = "SELECT %(author_id)s::uuid AS user_id"


class PostgresSource:
    def __init__(self, conn, settings):
        self.conn = conn
        self.settings = settings
        if settings.recipient_mode == "self_test":
            self.candidates_sql = AUTHOR_SQL
        else:
            path = (Path(__file__).resolve().parents[1] / "sql" / "recipients.sql"
                    if settings.recipient_mode == "friends" else Path(settings.recipients_file))
            self.candidates_sql = path.read_text(encoding="utf-8").strip().rstrip(";")
            if not self.candidates_sql:
                raise ValueError(f"Empty recipients SQL file: {path}")

    @contextmanager
    def snapshot(self):
        """Finish all PostgreSQL reads before making any network writes."""
        with self.conn.transaction():
            self.conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            yield

    def get_post(self, post_id):
        return self.conn.execute(
            "SELECT id, author_id, created_at, visibility, kind, shared_post_id, deleted_at "
            "FROM public.posts WHERE id = %s::uuid", (post_id,),
        ).fetchone()

    def recipient_ids(self, post):
        # Only trusted, operator-written SQL is inserted here; never request data.
        # Candidate scope (friends/followers) is distinct from permission to view.
        # PRIVATE can only reach the author; avoid scanning their friendships.
        candidates_sql = AUTHOR_SQL if post["visibility"] == "PRIVATE" else self.candidates_sql
        query = f"""
            WITH selected_candidates AS ({candidates_sql}),
            candidates AS (
                SELECT user_id FROM selected_candidates
                UNION SELECT %(author_id)s::uuid AS user_id
            )
            SELECT u.id AS user_id
            FROM candidates c
            JOIN public.users u ON u.id = c.user_id
            WHERE u.status = 'ACTIVE' AND u.deleted_at IS NULL
              AND public.can_view_post(%(post_id)s::uuid, u.id)
              AND NOT EXISTS (
                  SELECT 1 FROM public.hidden_posts h
                  WHERE h.user_id = u.id AND h.post_id = %(post_id)s::uuid
              )
            ORDER BY u.id
            LIMIT %(recipient_limit)s
        """
        rows = self.conn.execute(query, {
            "author_id": str(post["author_id"]),
            "post_id": str(post["id"]),
            # Available to custom SQL. can_view_post already checks the original
            # of a SHARE, including its author, visibility and deleted state.
            "original_id": str(post["shared_post_id"])
            if post["kind"] == "SHARE" and post["shared_post_id"] is not None else None,
            "recipient_limit": self.settings.max_recipients + 1,
        }).fetchall()
        if len(rows) > self.settings.max_recipients:
            raise RuntimeError("Audience exceeds MAX_RECIPIENTS_PER_EVENT; split into durable jobs")
        return [str(row["user_id"]) for row in rows]
