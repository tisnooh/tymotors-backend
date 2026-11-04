-- Data correction only: reviewed supplier evidence, not a product approval.
-- Re-runnable: row lock + source marker prevent duplicate note/audit entries.
-- No supplier remapping, public price, image, stock or fitment change.
WITH previous AS MATERIALIZED (
  SELECT product_id, notes
  FROM public.product_supplier_data
  WHERE product_id = 'e46bf5e1-d459-44ca-b28d-70c01c5c14e7'::uuid
  FOR UPDATE
), changed AS (
  UPDATE public.product_supplier_data AS target
  SET notes = concat_ws(E'\n\n', nullif(previous.notes, ''),
    $evidence$SOYINTECH_PARTIAL_EVIDENCE_2026_11_04_GMAIL_1a1a53ecf2cf214d:
Alternative offer MR3BF2021, Nicy/Soyintech, email received 2026-11-04 07:28 Europe/Paris, Gmail 1a1a53ecf2cf214d (thread 1a1621f1af2501cc). Latest price USD 16 for one left/right pair, superseding the older USD 18 proposal in the historical note above; no EUR conversion or landed-cost claim. Supplier states F30 sedan 2013-2018 fitment; exact mirror/equipment exclusions and offered finish are NOT confirmed. Do not generalise to every F32 or other variant. One-pair dimensions/weight stated as 32x22x17 cm / 0.6 kg; packed dimensions and gross weight remain unconfirmed. MOQ 1 pair; individual boxes may be sent to a third-party China warehouse; domestic freight depends on the actual address, normally 1-3 working days transit (not France delivery). Pre-dispatch inspection/photos offered; post-delivery defect/wrong-item remedy, current stock/dispatch, quote validity, exact gloss-black ABS replacement variant and itemised France/CJ costs remain pending.
Provenance clarification: Nicy's 2026-11-03 reply (quoted in this email) confirms Yooyi belongs to Soyintech; this resolves the prior seller-relationship question, not equivalence to the current Leju primary offer. Updated supplier URL communicated in the existing correspondence: https://www.alibaba.com/product-detail/ABS-Gloss-Black-Replacement-Mirror-Cover_1600834862867.html . Primary supplier/reference/source and numeric cost fields are intentionally unchanged. supplier_verified remains false; no commercial approval, stock, purchase or shipment authorised. Clarification already sent Gmail 1a1a6695622def89.$evidence$),
      last_checked_at = now()
  FROM previous
  WHERE target.product_id = previous.product_id
    AND position('SOYINTECH_PARTIAL_EVIDENCE_2026_11_04_GMAIL_1a1a53ecf2cf214d' IN coalesce(target.notes, '')) = 0
  RETURNING target.product_id, previous.notes AS previous_notes, target.notes AS updated_notes
), audit AS (
  INSERT INTO public.admin_audit (action, resource, metadata)
  SELECT 'product.supplier_partial_evidence_recorded', product_id::text,
    jsonb_build_object(
      'actor', 'codex_user_authorised_catalogue_followup',
      'source_gmail_id', '1a1a53ecf2cf214d',
      'clarification_sent_gmail_id', '1a1a6695622def89',
      'supplier_candidate_reference', 'MR3BF2021',
      'price_amount', 16, 'price_currency', 'USD', 'sales_unit', 'left_right_pair',
      'supplier_verified_changed', false,
      'previous_notes', previous_notes, 'updated_notes', updated_notes)
  FROM changed
  RETURNING id
)
SELECT (SELECT count(*) FROM changed) AS updated_rows,
       (SELECT count(*) FROM audit) AS audit_rows;
