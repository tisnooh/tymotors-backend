# TYMotors — supplier inbox MVP (STAGING ONLY)

This addition extends the **existing** FastAPI + Supabase backend and React admin.
It does **not** connect to a personal WhatsApp account, does **not** automate
Alibaba.com chats, and does **not** contact a supplier without an explicit admin
action. Nothing here deploys to production.

## 1. Configure Meta WhatsApp Cloud API

In Meta for Developers, prepare an app with WhatsApp Cloud API, a Meta business
portfolio, a WhatsApp Business Account (WABA), a **test or dedicated business
number** and WhatsApp messaging permissions. Account eligibility, pricing,
business verification and Business App co-existence must be checked in Meta.

Follow the official documentation:
https://developers.facebook.com/docs/whatsapp/cloud-api/
https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api

Backend secrets (Render staging environment, never Vercel frontend or Git):
- `WHATSAPP_APP_SECRET`: Meta application secret, used to verify webhook HMAC.
- `WHATSAPP_VERIFY_TOKEN`: arbitrary long unpredictable value created by you.
- `WHATSAPP_ACCESS_TOKEN`: server-side access token with required permission.
- `WHATSAPP_PHONE_NUMBER_ID`: Meta Cloud API phone_number_id.
- `WHATSAPP_GRAPH_API_VERSION`: Graph API version currently supported by Meta.
- `WHATSAPP_OUTBOUND_ENABLED=false`: default off; enable only after testing.

Webhook callback: `https://<YOUR-STAGING-BACKEND>/api/whatsapp/webhook`.
Set the same verify token in Meta and subscribe to the `messages` field.
The endpoint validates Meta's `X-Hub-Signature-256` on all inbound POSTs.

**Important:** Your usual WhatsApp personal number does not automatically
become available to Cloud API. A WhatsApp Business App / API coexistence
migration is possible only where Meta/provider onboarding allows it.
Never share secret tokens in chat, screenshots, Git or browser JS.

## 2. Apply SQL in staging Supabase

Apply `supabase/migrations/202610210001_supplier_inbox.sql` to the staging
project. It creates private `supplier_contacts` and `supplier_messages` tables.
No public / authenticated browser RLS grants.

## 3. Use the TYMotors admin UI

After staging preview deployment, visit `/admin/suppliers`:
1. Add your preexisting Alibaba supplier with an international WhatsApp number.
2. Store their Alibaba profile URL. No Alibaba password or cookie required.
3. Check the explicit WhatsApp messaging permission only if it is genuinely given.
4. Receive signed WhatsApp messages from **known** suppliers in the inbox.
5. Write a draft, inspect it and click **Valider et envoyer**.
6. Free-form sending is blocked outside the 24h window since the last inbound
   supplier WhatsApp message; templates aren't implemented in MVP.
7. For Alibaba inbox, open supplier's Alibaba URL, manually copy relevant
   exchanges into the 'Alibaba (manuel)' records. **No automated Alibaba send.**

## 4. MVP API endpoints

- GET /api/whatsapp/webhook — Meta challenge (verify token).
- POST /api/whatsapp/webhook — signed inbound webhook.
- GET /api/admin/suppliers — admin list.
- POST /api/admin/suppliers — create known contact.
- PATCH /api/admin/suppliers/{uuid} — update notes, consent or Alibaba URL.
- GET /api/admin/suppliers/{uuid}/messages — recent 100 messages.
- POST /api/admin/suppliers/{uuid}/messages — create WhatsApp draft or
  manually record Alibaba conversation.
- POST /api/admin/supplier-messages/{uuid}/approve-send — admin-approved
  outbound WhatsApp text (requires Meta configuration, consent and 24h window).

All /api/admin routes reuse server-side `require_admin` (Supabase Auth + profile).

## 5. Expected economics + limits

At launch, **no actual supplier orders or payments** are placed by the agent.
WhatsApp Business Platform price changes are controlled by Meta and may vary
by category/recipient country. Validate costs inside Meta before enabling live sends.
Alibaba public Open Platform has developer/application approval and permission
requirements, but an Alibaba.com **buyer chat sending/receiving API accessible to
this account is not yet verified**:
https://openapi.alibaba.com/doc/doc.htm

A phase-2 AI assistant can suggest translated drafts and product comparisons,
but MUST retain explicit human approval, clear provenance and a spend cap.
Do not bypass Alibaba/WhatsApp controls through scraping, cookie reuse or
unofficial WhatsApp libraries.

## 6. Security and QA checklist

- [ ] Apply migration in **staging only**, confirm RLS protections.
- [ ] Run `pytest -q tests/test_supplier_inbox.py`; run full test suite too.
- [ ] Confirm Meta verification works and signed webhooks are accepted.
- [ ] Confirm invalid signatures and unknown contacts are ignored/rejected.
- [ ] Confirm same webhook event repeated is idempotent.
- [ ] Confirm drafts aren't sent with `WHATSAPP_OUTBOUND_ENABLED=false`.
- [ ] Confirm no send if supplier consent absent or 24h service window expired.
- [ ] Test one known opt-in supplier's incoming and outgoing WhatsApp messages.
- [ ] Check Render logs for API errors; do not print WhatsApp body, credentials.
- [ ] Review cancellation, retention/GDPR and supplier privacy notice before
      production use.
- [ ] Merge neither preview branch into production until manual review and tests.

## 7. What is NOT implemented

- Alibaba automatic messages / chat sync (API and account access unconfirmed).
- Meta template messaging outside 24h, media and attachments.
- AI-generated replies, automated negotiations or bulk outreach.
- Fulfillment, invoicing, supplier payments, per-SKU sync.
- Full WhatsApp history import before connecting Cloud API.
