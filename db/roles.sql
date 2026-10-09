-- The platform's database roles (design.md, section 14). Roles are shared by every database on a server, so
-- this runs once per server as a superuser, before the migrations. Logins and passwords are set by the server
-- setup script; this file only makes sure each role exists without privileges of its own.
DO $$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['psst_platform_admin', 'psst_platform_system', 'psst_platform_worker',
                                     'psst_platform_publisher', 'psst_platform_console', 'psst_platform_api']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', role_name);
        END IF;
    END LOOP;
END
$$;
