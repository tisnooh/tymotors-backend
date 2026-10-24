# Durable sandbox attempts and shadow reservations

Migration: `20261024073311_commerce_checkout_attempts.sql`, created by the Supabase CLI. Scope: **local, TEST-only preparation**. There is no provider SDK, network call, real payment, stock decrement, supplier instruction, session reconciliation or completed checkout in this migration. No catalogue products are commercially validated by it.

## Private storage

Both public-schema tables have RLS enabled, no public/client policies, no `PUBLIC`/`anon`/`authenticated` privileges. Only the trusted backend service role has SELECT/INSERT/UPDATE. Every RPC and helper is `SECURITY INVOKER`, `search_path=''`, explicitly revoked from clients. Admin RPCs additionally check the actor's **current profiles row**, not editable JWT metadata, and check again after their profile/source barrier.

`commerce_checkout_attempts` has a UUID identity, one attempt per order, immutable order/quote IDs, test flag TRUE, EUR total (50..99,999,999 cents), integer epoch `expires_at`, actual quote expiration, canonical server frontend origin, unique random integration identifier (`tymotors_test_` plus eight letters) and durable unique idempotency key (`tymotors-test-<attempt UUID>`). The random suffix is generated from database UUID entropy and is frozen; it is not a secret or an authorization capability. Parameters and their SHA-256 over PostgreSQL's canonical JSONB text are nullable until first storage. This hash is not a signature and must not be compared with differently serialized Python JSON. There are immutable first-request timestamps and reserved future test-session fields. Records cannot be deleted/truncated, including through the service role. Database-owner disabling of guards is outside the trust model.

`commerce_variant_reservations` stores `(attempt_id, variant_id, offer_id)` with quantity, TRUE test flag, held/released/consumed state and timestamps. Identities, quantity and creation timestamp never change. An inserted hold must correspond exactly to a variant group and aggregate quantity in the attempt's quote. The only implemented update is held→released after safe draft cancellation. No consumed transition or payment fulfillment is enabled. Foreign keys RESTRICT deletion of historical records.

Partial indexes cover held variant and held offer quantities. Quantities are counted **separately by variant and by supplier offer**, across all attempts. No expiry predicate silently removes holds. An expired draft is conservatively held until explicit cancellation; creating/unknown reservations cannot be cancelled or freed because local time elapsed. These are a **test inventory namespace**, not reservations against real customer stock. Real stock and real supplier availability remain unchanged. Live checkout must never reuse them as real stock allocation.

## RPC contracts

All functions accept a current admin actor and are service-only. JSON return values below are private backend data; the API must use its explicit admin projection, never return keys/provider parameters indiscriminately.

`commerce_prepare_checkout_attempt(p_actor uuid,p_order_id uuid,p_frontend_origin text) -> {attempt,order,items}`

- Original cart must exist, with the original quote owner. Quote must be consumed by the same pending/unpaid test order; totals, EUR, destination and owner must still match. Public item count/content must match the immutable quote/private line snapshots, with no forged extra item. `order` is the raw row enriched with the **related quote's** `quote_expires_at`; `items` are raw persisted order items sorted by UUID.
- For a **new** attempt, exact source is recaptured and compared, the existing independent SQL quote validator runs again, and remaining quote life must be at least 31 minutes. No source retargeting or quote renewal occurs. Expiry is floor(epoch of the original quote expiry), never beyond it. The volatile 31-minute check belongs in this RPC, not a table CHECK.
- Held quantities plus requested grouped quantity must fit both variant stock and offer available quantity. Attempt, holds and one audit event are atomic. Duplicate preparation returns the original attempt without reinterpreting changed prices or rebuilding parameters; frontend origin changes are rejected. A missing/detached cart blocks new preparation and claim. A separate admin GET can still inspect persisted attempts.
- Origins must be canonical server configuration, not browser-supplied redirect URLs. SQL accepts HTTPS authority and HTTP localhost/127.0.0.1/[::1] with optional port, no path/query/fragment. The pure Python builder additionally validates public authority and port rules before storing parameters; unsupported origins lead to safe draft cancellation, not a provider call.

`commerce_store_checkout_params(p_actor uuid,p_attempt_id uuid,p_params jsonb) -> attempt`

Drafting→ready, write-once. SQL independently reconstructs **the complete provider option object** from the persisted, sorted order items, frozen attempt and order. Exact JSONB equality rejects extra/missing keys as well as altered currency, quantity/price, order/quote/attempt/product/variant/item metadata, destination country, shipping, expiry, integration identifier or redirects. Fixed-amount EUR inclusive shipping and line tax behavior, disabled automatic/adaptive tax and promotions, billing required and dynamic payment methods are preserved. Included tax is not added a second time. Goods sums are checked against the order. The history guard also enforces exact initial parameter content and SHA-256. Same params retry returns stored data without a second audit; differing data fails. A draft with less than 30 minutes creation window cannot be stored. No idempotency key is regenerated.

The builder remains the boundary for image URL/known-source-denial rules, complete address validation and supported-country semantics; exact SQL image membership/value is not a photographic licence or image authentication. The service must build the payload itself from this private context, never forward a client-supplied object. SQL storage does not authorize calling a provider.

`commerce_claim_checkout_attempt(p_actor uuid,p_attempt_id uuid) -> attempt`

Ready→creating **once**. Rechecks pending order/owner, remaining ≥30 minutes, exact current source and quote validity through the frozen attempt expiry, complete own reservation coverage and both accumulated inventory limits. Own holds are excluded from the competing sum, not from existence/quantity checks. Parameters must still match the immutable order. First-request time and one audit are persisted atomically **before any future remote request**. A second claim, cancelled, unknown or already creating attempt is refused. The future adapter must not interpret a rejected second claim as permission to make a second provider request.

`commerce_checkout_unknown(p_actor uuid,p_attempt_id uuid,p_error_code text) -> attempt`

Creating→unknown; preserves original params/key/first-request time and every hold. Allowed technical codes only: `provider_timeout`, `provider_connection_error`, `provider_response_unknown`, `worker_interrupted`, `idempotency_conflict`, `provider_unavailable`, `unclassified_provider_error`. Raw exceptions, addresses, emails and arbitrary error text are not stored. A reconciliation workflow is still required; this RPC cannot establish that no provider call occurred.

`commerce_cancel_checkout_draft(p_actor uuid,p_attempt_id uuid) -> attempt`

Drafting/ready→cancelled only while first-request time is NULL. Cancels and releases held rows in one transaction/audit; repeating cancellation is idempotent. It deliberately does **not** require a surviving cart or mutate the public order status/financial header. This permits cleanup of a never-claimed draft after cart purge. Creating/unknown/session-created attempts are never freed through this function. Financial amounts, `is_test` and quote identity remain protected by the preceding quoted-order migration.

`session_created` is a reserved persisted state, **not reachable by an implemented transition**. Session IDs/URLs, payment confirmations, consumed holds, webhooks, durable event deduplication, settlement and supplier fulfillment require a separately reviewed migration/service. The database currently permits no direct mutation of session fields.

## Locking and history

Preparation/store/claim discover order/quote without row locks, then use **cart→quote→order**, rechecking owner and snapshots. They take the preceding quote source barrier (`cart_items→profiles→products→product_images→product_variants→supplier_offers→shipping_rates→commerce_agents→suppliers→variant_compatibilities→product_compatibilities→brands→vehicle_models→vehicle_generations`) in EXCLUSIVE NOWAIT mode, followed by `profiles→order_items→commerce_checkout_attempts→commerce_variant_reservations` in EXCLUSIVE NOWAIT mode. Existing source locks may be reacquired. Ordinary SELECT remains possible. Writers and FK/row-lock upgrades conflict; failure returns safe P0001 `Commerce source busy; request a fresh quote` or `Commerce attempt busy; retry safely`, which the service maps to conflict, not a blind retry/claim.

Cancellation/unknown need no cart and take the latter barrier only, including profiles before their audit FK, then recheck current admin. Private `commerce_order_lines` keeps its existing SELECT/INSERT-only privileges: no UPDATE grant was added just to take a table lock. Those snapshots cannot update/delete; their order FK conflicts with the locked parent order during preparation/store/claim, and their content is compared to quote lines.

No external work is performed under these deliberately conservative, short global barriers. The migration is transaction-wrapped. Any validation failure rolls back inserted attempts, holds, transitions and audit together. Broad barriers can cause contention: optimizing them requires a real multi-connection review, not assuming single-process tests prove deadlock freedom.

## Verification and remaining integration gates

```powershell
node tests/commerce_attempt_database.mjs
```

The test imports pinned `tools/sql-tests` PGlite first (committed version/lock); historical ignored runtimes are fallbacks only, never automatically installed. It loads the real migration chain with disposable auth stubs and synthetic products, no hosted database/secrets/network. It tests two-order accumulated demand, independent supplier/variant limits, exact params and immutable keys, source changes between prepare/claim, one claim and uncertain outcome, safe/idempotent cancellation including detached cart, locally expired holds, forged public lines, client grants/current-admin checks, actual ExclusiveLock presence, audit counts, and unchanged real inventory/payments/supplier queue.

PGlite is real PostgreSQL execution but single-session: it does **not** prove multi-connection contention, row/table interleavings, hosted PostgREST grants, Stripe account settings or provider idempotency retention. No payment SDK has been integrated, and the admin preparation endpoint must continue to report payment unavailable. A future remote adapter must review claim/reconciliation semantics, signatures/event replay, full destination match, order/payment transition atomicity and test/live isolation before enabling any call.

Official current references consulted before implementation: [Supabase functions](https://supabase.com/docs/guides/database/functions), [changelog](https://supabase.com/changelog). Markdown changelog transport was unsupported; the HTML index was used. Current notices did not change this invoker/RLS SQL contract; no hosted upgrade or CLI update was attempted.
