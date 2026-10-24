# Private quote snapshots — SQL contract

Source migration: `20261024012206_commerce_quote_snapshots.sql`. This is local implementation and disposable PostgreSQL verification, not evidence of a hosted migration, live payment capability, stock reservation, supplier selection authorization or completed checkout.

## Source capture

`commerce_cart_context(p_cart_id uuid, p_user_id uuid, p_guest_session text, p_country text, p_postal_code text, p_mode text) -> jsonb` is service-only and `SECURITY INVOKER`. It reuses `private.assert_cart_owner`: precisely one real user or a guest capability owns the cart. Country is uppercase two letters, postal code 1–20 ASCII letters/digits/spaces/hyphens, and mode 1–100 nonblank characters. Owner mismatch fails, rather than returning another cart's existence or private costs.

The `STABLE` function returns a coherent statement snapshot, UTC timestamp representation and raw, complete rows. Object keys: `cart`, `country`, `postal_code`, `mode`, `cart_items`, `products`, `product_images`, `variants`, `offers`, `rates`, `agents`, `suppliers`, `links`, `compatibilities`, `brands`, `models`, `generations`. Arrays are sorted by `id`; links by `(variant_id, compatibility_id)`. Offers are all offers for the cart variants, not only a favored supplier. Rates include **all** country/mode rules for those offers, including regional prefixes. Rules include all compatibility rows for the products, not only selected links. Thus inserting a regional restriction or product rule changes the context.

Counts are exact: over 100 cart lines, 1,000 offers, 1,000 destination/mode rates or 1,000 product rules causes an error. No `LIMIT` silently hides a restriction. Other arrays contain their full referenced rows. This JSON includes supplier costs, evidence references and internal configuration: never return it or the private payload through a customer API.

## Short locking protocol

Both write RPCs lock the cart before a quote row. Preparing an order first reads its quote without a lock to discover the cart, then locks cart and quote and rechecks ownership. Every write-source barrier uses the same table order:

`cart_items → profiles → products → product_images → product_variants → supplier_offers → shipping_rates → commerce_agents → suppliers → variant_compatibilities → product_compatibilities → brands → vehicle_models → vehicle_generations`.

The conservative barrier is `EXCLUSIVE MODE NOWAIT`, not `SHARE`. It blocks `ROW SHARE` and writers as well as insert/delete phantoms, but allows ordinary `SELECT`. This prevents waiting for a source/FK row held by an administrator who is subsequently waiting to upgrade a table lock. `profiles` is included because order/audit foreign keys otherwise introduce a profile-delete/cart-cascade lock cycle. No HTTP, Stripe or supplier operation happens under these locks.

A conflicting lock is caught and converted to `P0001` with the safe message `Commerce source busy; request a fresh quote`. The service must map it to a business conflict (409), not expose database details. Acquisition failure aborts the statement/transaction, rather than retaining a partly saved quote. This intentionally serializes source writers briefly and can cause contention; row-level optimization requires a separate multi-connection review. PGlite is a real single-session PostgreSQL engine, **not** proof of all concurrent interleavings or deadlock absence. Tests inspect actual `ExclusiveLock` acquisition, while multi-connection contention remains an integration verification requirement.

The barrier is followed by a fresh source capture and exact JSON equality. Any changed value, deleted row or newly matching regional row rejects the original quote source. No source rule row locks are acquired inside this barrier; compatibility link integrity is checked from the frozen context instead.

## Save protocol

`commerce_save_quote(p_cart_id uuid, p_user_id uuid, p_guest_session text, p_request_key uuid, p_destination jsonb, p_mode text, p_source jsonb, p_payload jsonb) -> quote row jsonb`.

Destination includes `country` and `postal_code`. Payload is the private engine contract:

```text
{groups:[{variant_id,offer_id,shipping_rate_id,responsible_agent_id,supplier_id,
          line_ids:[UUID],evaluation:{quote_offer result},lines:[{cart_item_id,
          product_id,variant_id,quantity,unit_amount_cents,sku,product_name,
          product_slug,image_url,selected_vehicle,compatibility_result,
          variant_name,variant_attributes}]}],
 subtotal_cents,shipping_cents,tax_cents,total_cents,currency:'EUR',valid_until:ISO}
```

SQL independently checks every persisted line occurs exactly once, group/line identities, price/SKU/name/attributes and vehicle identity, source image membership, product/variant verification and explicit EUR currencies. It checks aggregated variant and supplier stock/MOQ, live verified offer/rate evidence, responsible active order agent, source expiry/FX terms, quantity band and the uniquely most-specific regional rate. Different variants from one supplier require `shipping_rates.multi_variant_policy='independent_parcels'` for **each** chosen rate; default `unknown` does not authorize aggregation. The existing `admin_save_commerce_record` gains this whitelist/default/update field through three asserted definition anchors; unexpected old RPC drift aborts the migration rather than silently skipping the amendment.

Fine vehicle-fitment decisions and lawful image selection are still computed by the reviewed Python engine using the existing compatibility/picture policies. SQL checks source/link ownership, verified rules, persisted vehicle identity and the resulting per-line status; it does not claim to reimplement the whole automotive matcher or establish legal rights. The caller must only submit a server-built payload, never forward one supplied by the browser.

The SQL recomputes acquisition, recoverable taxes, exchange rounding, logistics, destination-specific goods/shipping tax components, contribution margin and customer totals. It compares the engine evaluation with those values. Costs remain private. Money is integer cents; supported customer amounts are 0–2,000,000,000. `null` never becomes a free charge or tax assumption. `total_cents = subtotal_cents + shipping_cents`; tax is **already included**, not added again. FX/currency and monetary tampering are rejected.

All conditions must remain valid at least 35 minutes at initial save. Stored expiry is `min(source valid_until, captured clock + 45 minutes)`. Payload validity must be the exact earliest selected offer/rate/applicable-FX expiry and include a timezone. Idempotency is `(cart_id,request_key)`: same owner and identical destination/mode/source/payload returns the original snapshot, even if now superseded, consumed or expired. Different content with that key fails. Retries never reinterpret old prices. New successful snapshots supersede the older ready quotes for that cart. Creation has one existing `admin_audit` event; idempotent retries do not duplicate it.

## Immutability and owner history

`commerce_quotes` stores source, payload, destination, included tax, totals, original user UUID or guest capability, request key, expiry and timestamp. There is no owner-profile FK that would rewrite history. RLS is enabled; `PUBLIC`, `anon` and `authenticated` have no table or RPC access. Service role receives only required select/insert/update permissions, no delete/truncate grant.

Quote data cannot be edited even through service role. Initial state is `ready`; the only state transitions are `ready → superseded` when a newer ready snapshot exists and `ready → consumed` after its unique pending test order exists. History cannot be deleted or truncated. A cart FK can only detach to NULL when the cart is actually deleted; its embedded original cart/source/owner remain unchanged. A detached quote is unusable, including after a guest-cart claim deletes the old cart. No operation reattaches or transfers that snapshot to a new cart.

The service role is a privileged backend trust boundary for inserts, not a customer capability. All application quote writes must use the guarded RPC; never expose service keys or permit arbitrary direct snapshot inserts. Database-owner disabling of triggers is outside this protection model.

## Test-order primitive, not checkout

`commerce_order_from_quote(p_actor uuid, p_quote_id uuid, p_user_id uuid, p_guest_session text, p_is_test boolean) -> {order_id,order_number,quote_id,is_test,reused}`.

This is service-only and **admin-only inside SQL**, including a fresh actor-role check under the source barrier for a new order. `p_is_test` must be exactly TRUE; false/NULL raises. It verifies the original owner and existing cart, ready unexpired quote and unchanged recaptured source. It creates exactly one `orders` row for a quote (`commerce_quote_id` unique), explicitly pending/unpaid/test, compatibility-review required. Retry returns that same order without another line or audit event.

Public `order_items` receive only product/variant presentation, quantity, customer unit price, selected vehicle and result, `variant_name`, `variant_attributes`, and historical `source_cart_item_id`. They receive no offer/rate/agent costs; existing `cost_price_cents` remains NULL. Private `commerce_order_lines` store immutable quote/group/line and original offer/rate/agent/supplier snapshots. Source rows can later change without rewriting those snapshots. Quoted public line content, including quantity/unit amount and product/variant/source identity, cannot subsequently be rewritten. Foreign keys use RESTRICT to prevent silent snapshot loss. The quoted order header freezes quote identity, subtotal/shipping/tax/total/currency and `is_test`; an admin bug cannot switch it into real fulfillment. Ordinary status/payment/customer-metadata updates and cart/owner FK detachment remain possible; normal legacy orders are not globally frozen.

No payment is recorded, no Stripe call occurs, no inventory is reserved/decremented, no supplier queue/order is created and no shipment is initiated. Existing sandbox stock/fulfillment protections remain in force. This primitive must not be described as completed customer checkout or authorization to purchase.

## Local verification

```powershell
node tests/commerce_quote_database.mjs
```

The test first imports the pinned `tools/sql-tests` runtime (PGlite 0.5.8 with its committed lockfile); historical local `.admin-test-runtime` locations are fallbacks only. Dependency installation in clean CI is explicit (`npm ci --prefix tools/sql-tests`), never an automatic test-side installation. It loads the actual migration chain and uses synthetic products/suppliers, never the forty real catalogue articles. It covers source price/rule/region insert changes, count limits, invalid amounts/currency and incomplete line coverage, owner and request-key checks, stale/superseded quotes, stock/MOQ/validity, real role grants and immutable service-role snapshots, test-order retry/audit/no-stock/no-supplier side effects, cart deletion and preserved private history. Auth users/sessions are disposable stubs, not a claim of hosted Auth/PostgREST acceptance. Production application, external APIs and concurrent multi-connection behavior require separately authorized verification.
