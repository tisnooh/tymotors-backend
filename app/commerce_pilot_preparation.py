"""Private pilot preparation, never a catalogue import or supplier approval.

Reuse the existing five-pilot selection, copy review and commerce contracts.
Only a draft variant preview is schema-valid. Offer/shipping templates remain
deliberately invalid where evidence is missing; None is never a free charge.
"""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import re
from uuid import UUID

from pydantic import ValidationError

from app.commerce_dossiers import ORIGINAL_SUPPLIERS, PILOTS
from app.commerce_models import OfferInput, ShippingRateInput, VariantInput


PILOT_CHECKLISTS = {
    'bmw-f30-m-performance-spoiler': {
        'mounting': ['Confirmer coffre/carrosserie, fixations et accessoires de pose.',
                     'Réconcilier 2013–2018 déclaré par Soyin avec 2013–2019 archivé.',
                     'Identifier finition et variante ; aucun gain aérodynamique établi.'],
        'extensions_not_proved': ['F30 année 2012', 'F30 année 2019 sur ce SKU Soyin', 'Break F31'],
    },
    'bmw-f30-f32-mirror-caps': {
        'mounting': ['Vérifier forme/référence des rétroviseurs et leurs équipements.',
                     'Distinguer remplacement et surcoque ; confirmer gauche/droite et finition.',
                     'Respecter les plages distinctes F30/F31 et F32/F33/F36 déclarées, sans extension automatique.'],
        'extensions_not_proved': ['Toutes années de tous les châssis cités', 'Tous équipements de rétroviseurs',
                                  'Toutes configurations LHD/RHD'],
    },
    'bmw-g20-m-performance-spoiler': {
        'mounting': ['Confirmer coffre et carrosserie G20/G28, fixations et accessoires de pose.',
                     'Faire préciser la limite finale de 2019+ et les phases couvertes.',
                     'Identifier la finition et le style exact du SKU proposé.'],
        'extensions_not_proved': ['Break G21', 'Toutes phases postérieures à 2019', 'Gain aérodynamique'],
    },
    'mercedes-w205-mirror-caps': {
        'mounting': ['Confirmer référence/forme du rétroviseur, phase et équipements.',
                     'Distinguer remplacement et surcoque ; confirmer côtés et finition.',
                     'Ne pas étendre la déclaration W205 2015–2018 aux autres années ou châssis sans preuve propre.'],
        'extensions_not_proved': ['Toutes années W205', 'W213/W222/GLC par équivalence visuelle',
                                  'Toutes configurations LHD/RHD'],
    },
    'vw-golf7-mirror-caps': {
        'mounting': ['Clarifier le libellé exact « 14-16 Molk 7 Lamando » sans le corriger arbitrairement.',
                     'Confirmer modèle/phase, référence et équipements des rétroviseurs.',
                     'Distinguer remplacement et surcoque ; confirmer côtés et finition.'],
        'extensions_not_proved': ['Toute Golf 7/Mk7.5 2013–2019', 'Touran/Sportsvan par simple extension',
                                  'Toutes configurations LHD/RHD'],
    },
}

COMMERCIAL_MISSING = [
    'Fournisseur/SKU/variante retenus et rattachement à la variante interne.',
    'Unité commerciale exacte, quantité/contenu et finition.',
    'Prix fournisseur, devise, MOQ/paliers, validité et disponibilité.',
    'Poids/dimensions emballés, préparation, port et délai direct France.',
    'Incoterm, taxes/frais détaillés, retours et garantie.',
    'Responsable opérationnel et approbation administrateur avant tout import réel.',
]


def _dated(value, label):
    if not isinstance(value, str):
        raise ValueError('Missing dated evidence: ' + label)
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid evidence timestamp: ' + label) from exc
    if 'T' not in value or result.utcoffset() is None:
        raise ValueError('Evidence timestamps require time and timezone: ' + label)
    return result


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _indexed(rows, key, label):
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get(key), str)
                                         or not row[key].strip() for row in rows):
        raise ValueError('Invalid ' + label)
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate ' + label)
    return result


def _incomplete_template(model, data):
    """Expose actual contract gaps, not fabricated IDs/defaults to pass import."""
    try:
        model.model_validate(data)
    except ValidationError as exc:
        return {'schema': model.__name__, 'schema_valid': False, 'import_allowed': False,
                'data': data, 'missing_or_invalid_fields': sorted({str(error['loc'][0]) for error in exc.errors()})}
    raise ValueError('An incomplete candidate template unexpectedly became importable')


def prepare_pilot_catalogue(dossiers, soyin, *, prepared_at,
                            dossier_label='phoenix-2026-10-28-direct-shipping-v4/dossiers-40.json',
                            soyin_label='catalogue-review-2026-10-23/continuation/soyin-29-review.json'):
    """Build local, reviewable preparation packets without mutating any input."""
    as_of = _dated(prepared_at, 'preparation clock')
    observed = _dated(dossiers.get('observed_at'), 'catalogue observation')
    received = _dated(soyin.get('received_at'), 'Soyin reply')
    if observed > as_of or received > as_of:
        raise ValueError('Preparation cannot predate its evidence')
    articles = _indexed(dossiers.get('articles'), 'slug', 'catalogue articles')
    identities = []
    for row in articles.values():
        try:
            if not isinstance(row.get('product_id'), str):
                raise ValueError('Missing UUID')
            identities.append(str(UUID(row['product_id'])))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError('Invalid catalogue UUID') from exc
    if len(articles) != 40 or len(set(identities)) != 40:
        raise ValueError('Expected forty unique article identities')
    if (not isinstance(soyin.get('received_message_id'), str) or not soyin['received_message_id'].strip()
            or not isinstance(soyin.get('sha256'), str) or not re.fullmatch(r'[a-fA-F0-9]{64}', soyin['sha256'])):
        raise ValueError('Missing original supplier message or attachment hash')
    policy = dossiers.get('execution_policy') or {}
    if (policy.get('original_suppliers') != list(ORIGINAL_SUPPLIERS)
            or policy.get('publication_authorized') is not False
            or policy.get('photo_review') != 'DEFERRED_BY_OWNER'):
        raise ValueError('Expected the private three-original-supplier execution scope')
    pilots = {slug: row for slug, row in articles.items() if row.get('pilot_rank') is not None}
    if set(pilots) != set(PILOTS):
        raise ValueError('Pilot selection drift')
    findings = _indexed(soyin.get('findings'), 'slug', 'Soyin findings')
    prepared = []
    for rank, slug in enumerate(PILOTS, 1):
        article = pilots[slug]
        if type(article.get('pilot_rank')) is not int or article['pilot_rank'] != rank:
            raise ValueError('Pilot rank drift')
        try:
            UUID(article['product_id'])
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError('Invalid pilot UUID') from exc
        if (article.get('supplier_selected') is not None or article.get('supplier_selected_confirmed') is not False
                or article.get('compatibility_verified') is not False
                or article.get('catalogue_verified_observed') is not False
                or article.get('publication_status') != 'draft'
                or any(article.get(key) is not None for key in ('supplier_unit_cost_cents', 'supplier_currency',
                       'shipping_confirmed_cents', 'landed_cost_cents', 'gross_margin_cents', 'net_margin_cents'))):
            raise ValueError('Pilot evidence changed: review rather than replace confirmed data with unknowns')
        proposal = findings.get(slug)
        if not proposal or article.get('candidate_soyin') != proposal:
            raise ValueError('Soyin candidate drift: reconcile original evidence before preparing')
        if any(proposal.get(key) is not False for key in ('exact_same_product_proved', 'selected_supplier_variant',
                                                         'fitment_confirmed_for_tymotors', 'price_quote_present')):
            raise ValueError('Candidate evidence is not the reviewed unselected proposal')
        values, cells = proposal.get('source_values') or {}, proposal.get('cells') or {}
        if values.get('internal_code_raw') != slug:
            raise ValueError('Candidate internal code does not identify this pilot')
        for field in ('supplier_sku', 'material', 'fitment'):
            if not isinstance(values.get(field), str) or not values[field].strip():
                raise ValueError('Missing pilot candidate declaration: ' + field)
        if not proposal.get('sheet') or type(proposal.get('row')) is not int or not all(cells.get(k) for k in ('sku', 'material', 'fitment')):
            raise ValueError('Missing original candidate cell references')
        if any(not re.fullmatch(r'[A-Z]+' + str(proposal['row']), cells[k]) for k in ('sku', 'material', 'fitment')):
            raise ValueError('Candidate cell references point to another source row')
        offered_url = values.get('offered_url')
        if offered_url is not None:
            if not isinstance(offered_url, str):
                raise ValueError('Invalid candidate URL type')
            OfferInput.secure_url(offered_url)
        copy = article.get('proposed_copy') or {}
        if not all(isinstance(copy.get(k), str) and copy[k].strip() for k in ('title', 'subtitle', 'description')):
            raise ValueError('Missing reviewed catalogue copy')
        if (type(article.get('sale_price_cents_observed')) is not int
                or article.get('sale_currency_observed') != 'EUR'):
            raise ValueError('Missing unchanged public-price snapshot')
        if _dated(article.get('sale_price_observed_at'), 'public-price observation') > as_of:
            raise ValueError('Public-price observation is future dated')
        if not isinstance(article.get('sku'), str) or not article['sku'].strip():
            raise ValueError('Missing observed internal catalogue SKU')
        source_ref = soyin_label + '#' + proposal['sheet'] + '!' + cells['sku']
        variant = VariantInput(product_id=article['product_id'], sku=article['sku'], name=copy['title'],
                               price_cents=article['sale_price_cents_observed'], currency='EUR',
                               status='draft', stock=0, is_verified=False, is_default=False,
                               requires_vehicle=True, attributes={}, compatibility_ids=[],
                               sale_tax_bps=None, evidence_ref=None).model_dump(mode='json')
        offer = dict.fromkeys(OfferInput.model_fields)
        offer.update(supplier_sku=values['supplier_sku'], url=offered_url,
                     verification_state='pending', is_primary=False, availability='unknown')
        shipping = dict.fromkeys(ShippingRateInput.model_fields)
        shipping.update(country='FR', verification_state='pending', multi_variant_policy='unknown')
        prepared.append({
            'pilot_rank': rank, 'product_id': article['product_id'], 'slug': slug,
            'internal_catalogue_sku': article['sku'],
            'catalogue_copy': {**{key: copy[key] for key in ('title', 'subtitle', 'description')},
                               'action': 'KEEP_EXISTING_REVIEWED_COPY', 'patch': {},
                               'evidence_ref': article['sources']['copy']},
            'supplier_choice': {'initial_partners': list(ORIGINAL_SUPPLIERS),
                                'candidate_name': 'Soyintech / Soyin', 'candidate_reference': values['supplier_sku'],
                                'selected_supplier_id': None, 'selected_reference': None, 'selected_variant': None},
            'candidate_declarations': {
                'scope': 'supplier_candidate_only_not_actual_product_confirmation',
                'material': {'value': values['material'], 'evidence_ref': soyin_label + '#' + proposal['sheet'] + '!' + cells['material']},
                'fitment_text': {'value': values['fitment'], 'evidence_ref': soyin_label + '#' + proposal['sheet'] + '!' + cells['fitment']},
                'reference_evidence': source_ref, 'reply_received_at': soyin['received_at'],
                'source_message_id': soyin.get('received_message_id'), 'candidate_url': offered_url,
                'issues': deepcopy(proposal.get('issues') or []),
            },
            'actual_product_fitment': {'confirmed_rules': [], 'compatibility_verified': False,
                                       'restrictions_to_confirm': deepcopy(PILOT_CHECKLISTS[slug]['mounting']),
                                       'extensions_not_proved': deepcopy(PILOT_CHECKLISTS[slug]['extensions_not_proved']),
                                       'missing_conditions_are_not_proved_incompatibilities': True},
            'draft_variant_import_preview': {'schema': 'VariantInput', 'schema_valid': True,
                                             'import_allowed': False, 'data': variant,
                                             'note': 'Draft only; retain existing public price snapshot, no catalogue write. '
                                                     'Check existing variant/SKU uniqueness before any later authorized import.'},
            'public_price_observation': {'price_cents': article['sale_price_cents_observed'],
                                         'currency': article['sale_currency_observed'],
                                         'observed_at': article['sale_price_observed_at'],
                                         'changed': False, 'price_approval': False},
            'candidate_offer_template': _incomplete_template(OfferInput, offer),
            'direct_france_shipping_template': _incomplete_template(ShippingRateInput, shipping),
            'missing_fields': {'variant_identity': ['supplier_id', 'variant_id', 'exact_supplier_variant',
                                                   'unit_of_sale', 'finish', 'package_contents', 'mounting_conditions'],
                               'commercial': deepcopy(COMMERCIAL_MISSING)},
            'safety': {'commercially_verified': False, 'ready_to_sell': False, 'import_authorized': False,
                       'public_price_changed': False, 'images_modified': False, 'design_modified': False,
                       'database_modified': False, 'publication_authorized': False,
                       'photo_review': 'DEFERRED_BY_OWNER',
                       'stock_zero_is_a_draft_guard_not_a_supplier_availability_claim': True},
        })
    return {'prepared_at': prepared_at, 'purpose': 'PRIVATE_PILOT_IMPORT_PREPARATION_NOT_APPROVAL',
            'source_observed_at': dossiers['observed_at'],
            'sources': {'dossiers': dossier_label, 'dossiers_canonical_sha256': _digest(dossiers),
                        'soyin_review': soyin_label, 'soyin_review_canonical_sha256': _digest(soyin),
                        'soyin_attachment_sha256': soyin.get('sha256'), 'soyin_received_at': soyin['received_at']},
            'summary': {'pilots': 5, 'draft_variant_previews': 5, 'incomplete_offer_templates': 5,
                        'incomplete_shipping_templates': 5, 'confirmed_actual_product_fitments': 0,
                        'commercially_verified_pilots': 0, 'imports_executed': 0, 'public_price_changes': 0,
                        'images_modified': 0, 'database_writes': 0, 'supplier_messages_sent': 0},
            'pilots': deepcopy(prepared)}
