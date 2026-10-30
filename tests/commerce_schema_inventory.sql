-- Read-only application schema metadata. No customer rows or secrets.
select kind, identity, definition from (
  select 'table' kind,c.relname::text identity,
    jsonb_build_object('rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity) definition
    from pg_class c join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relkind in ('r','p')
  union all
  select 'column',c.relname||'.'||a.attname,jsonb_build_object(
    'type',format_type(a.atttypid,a.atttypmod),'not_null',a.attnotnull,
    'default',pg_get_expr(d.adbin,d.adrelid),'identity',a.attidentity,'generated',a.attgenerated)
    from pg_attribute a join pg_class c on c.oid=a.attrelid
    join pg_namespace n on n.oid=c.relnamespace
    left join pg_attrdef d on d.adrelid=c.oid and d.adnum=a.attnum
    where n.nspname='public' and c.relkind in ('r','p') and a.attnum>0 and not a.attisdropped
  union all
  select 'constraint',c.relname||'.'||k.conname,to_jsonb(pg_get_constraintdef(k.oid))
    from pg_constraint k join pg_class c on c.oid=k.conrelid
    join pg_namespace n on n.oid=c.relnamespace where n.nspname='public'
  union all
  select 'index',tablename||'.'||indexname,to_jsonb(indexdef)
    from pg_indexes where schemaname='public'
  union all
  select 'policy',tablename||'.'||policyname,jsonb_build_object(
    'permissive',permissive,'roles',roles,'cmd',cmd,'qual',qual,'check',with_check)
    from pg_policies where schemaname='public'
  union all
  select 'function',p.oid::regprocedure::text,jsonb_build_object(
    'sql',pg_get_functiondef(p.oid),
    'anon',has_function_privilege('anon',p.oid,'EXECUTE'),
    'authenticated',has_function_privilege('authenticated',p.oid,'EXECUTE'),
    'service_role',has_function_privilege('service_role',p.oid,'EXECUTE'))
    from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.prokind='f' and not exists(
      select 1 from pg_depend d where d.classid='pg_proc'::regclass and d.objid=p.oid and d.deptype='e')
  union all
  select 'trigger',c.relname||'.'||t.tgname,to_jsonb(pg_get_triggerdef(t.oid))
    from pg_trigger t join pg_class c on c.oid=t.tgrelid
    join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and not t.tgisinternal
  union all
  select 'grant',table_name||'.'||grantee||'.'||privilege_type,to_jsonb(is_grantable)
    from information_schema.role_table_grants where table_schema='public'
    and grantee in ('anon','authenticated','service_role','PUBLIC')
) inventory order by kind,identity;
