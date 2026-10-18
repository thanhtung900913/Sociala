-- Home-feed candidates: the author's accepted friends in either side of the
-- ordered pair (user_low_id, user_high_id) defined in the PostgreSQL schema.
-- PostgresSource adds the author, excludes hidden posts, and calls can_view_post()
-- (which checks both the SHARE and its original).
-- RECIPIENT_MODE=friends uses this query by default.
SELECT f.user_high_id AS user_id
FROM public.friendships f
WHERE f.user_low_id = %(author_id)s::uuid
  AND f.status = 'ACCEPTED'

UNION ALL

SELECT f.user_low_id AS user_id
FROM public.friendships f
WHERE f.user_high_id = %(author_id)s::uuid
  AND f.status = 'ACCEPTED';
