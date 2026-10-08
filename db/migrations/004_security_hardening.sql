-- 004_security_hardening: Supabase exposes the public schema over its API, so lock down what 001-003 missed.

-- Views run with the caller's rights, so row-level security on the underlying tables still applies.
ALTER VIEW v_settled SET (security_invoker = true);

-- The migration bookkeeping table is internal: RLS on and no policy = invisible to API roles.
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;
