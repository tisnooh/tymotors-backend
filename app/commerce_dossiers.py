"""Evidence-only commercial dossiers; candidates are NEVER selected suppliers.

This is a private reporting projection, not a catalogue import or approval tool.
Missing confirmed costs stay null. Historical source timestamps are preserved.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import re
from uuid import UUID

PILOTS = (
    'bmw-f30-m-performance-spoiler', 'bmw-f30-f32-mirror-caps',
    'bmw-g20-m-performance-spoiler', 'mercedes-w205-mirror-caps', 'vw-golf7-mirror-caps',
)
PILOT_REASON = ('Candidat carrosserie sans électronique : SKU et matière proposés dans la réponse Soyin, '
                'sans conflit explicite signalé dans cette ligne. Cela ne prouve ni le même produit, '
                'ni le montage, ni les droits ; aucun fournisseur alternatif accepté.')


def _index(rows, key):
    if not isinstance(rows, list) or any(not isinstance(x, dict) or not x.get(key) for x in rows):
        raise ValueError('Invalid dossier source')
    result = {x[key]: x for x in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate dossier source')
    return result


def _closed_record(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('Invalid or unexpected fields in ' + label)


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError('Invalid text in ' + label)


def _timestamp(value, label):
    _text(value, label)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid timestamp in ' + label) from exc
    if 'T' not in value or parsed.utcoffset() is None:
        raise ValueError('Timestamp must include time and timezone in ' + label)
    return parsed


def _texts(value, label, *, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError('Invalid list in ' + label)
    for item in value:
        _text(item, label)


def _validated_reply_review(review, catalogue, *, as_of):
    """Validate declarations only; this schema has no commercial approval fields."""
    _closed_record(review, {'recorded_at', 'scope', 'articles'}, 'reply review')
    recorded_at = _timestamp(review['recorded_at'], 'reply review')
    review_clock = _timestamp(as_of, 'explicit reply review clock')
    if recorded_at > review_clock:
        raise ValueError('Reply review recorded_at is after the explicit review clock')
    if review['scope'] != 'candidate_supplier_evidence_only' or not isinstance(review['articles'], list):
        raise ValueError('Reply review must contain candidate evidence only')
    result, identities = {}, set()
    for row in review['articles']:
        _closed_record(row, {'product_id', 'slug', 'supplier_name', 'candidate_reference', 'reply_status',
                             'sources', 'confirmed_candidate_facts', 'documents', 'unresolved', 'next_action'},
                       'candidate article')
        for key in ('product_id', 'slug', 'supplier_name', 'next_action'):
            _text(row[key], key)
        try:
            UUID(row['product_id'])
        except ValueError as exc:
            raise ValueError('Invalid candidate product UUID') from exc
        slug = row['slug']
        if slug not in catalogue or catalogue[slug]['id'] != row['product_id']:
            raise ValueError('Candidate article identity mismatch')
        if slug in result or row['product_id'] in identities:
            raise ValueError('Duplicate candidate article')
        if row['candidate_reference'] is not None:
            _text(row['candidate_reference'], 'candidate reference')
        if row['reply_status'] != 'RESPONSE_INCOMPLETE':
            raise ValueError('Candidate reply must remain incomplete')
        if not isinstance(row['sources'], list) or not row['sources']:
            raise ValueError('Candidate reply needs identifiable message evidence')
        refs = set()
        for source in row['sources']:
            _closed_record(source, {'message_id', 'thread_id', 'received_at', 'evidence_ref'}, 'message source')
            for key in ('message_id', 'thread_id'):
                _text(source[key], key)
                if not re.fullmatch(r'[A-Za-z0-9_-]+', source[key]):
                    raise ValueError('Invalid message identity')
            received_at = _timestamp(source['received_at'], 'message source')
            if received_at > recorded_at:
                raise ValueError('Message received_at is after reply review recorded_at')
            ref = source['evidence_ref']
            if ref != 'gmail-message:' + source['message_id'] or ref in refs:
                raise ValueError('Invalid or duplicate message evidence reference')
            refs.add(ref)
        if not isinstance(row['confirmed_candidate_facts'], list):
            raise ValueError('Candidate facts must be a list')
        fact_ids = set()
        for fact in row['confirmed_candidate_facts']:
            _closed_record(fact, {'fact', 'value', 'evidence_refs', 'scope'}, 'candidate fact')
            _text(fact['fact'], 'fact name')
            _text(fact['value'], 'fact value')
            if not isinstance(fact['scope'], str) or fact['scope'] not in {'candidate_only', 'supplier_generic_claim'}:
                raise ValueError('Facts must not claim confirmation of the TYMotors product')
            _texts(fact['evidence_refs'], 'fact evidence', nonempty=True)
            if len(set(fact['evidence_refs'])) != len(fact['evidence_refs']) or not set(fact['evidence_refs']) <= refs:
                raise ValueError('Unbound candidate fact evidence')
            identity = (fact['fact'], fact['value'], fact['scope'], tuple(sorted(fact['evidence_refs'])))
            if identity in fact_ids:
                raise ValueError('Duplicate candidate fact')
            fact_ids.add(identity)
        if not isinstance(row['documents'], list):
            raise ValueError('Documents must be a list')
        document_ids = set()
        for document in row['documents']:
            _closed_record(document, {'filename', 'bytes', 'sha256', 'status', 'evidence_ref', 'checks'}, 'document')
            _text(document['filename'], 'document filename')
            if type(document['bytes']) is not int or document['bytes'] < 0:
                raise ValueError('Invalid document byte length')
            if not isinstance(document['sha256'], str) or not re.fullmatch(r'[a-fA-F0-9]{64}', document['sha256']):
                raise ValueError('Invalid document SHA-256')
            if document['status'] != 'UNREADABLE_INCOMPLETE':
                raise ValueError('Unreadable document must not become validated evidence')
            if not isinstance(document['evidence_ref'], str) or document['evidence_ref'] not in refs:
                raise ValueError('Unbound document evidence')
            _texts(document['checks'], 'document checks', nonempty=True)
            identity = (document['filename'], document['sha256'].lower(), document['evidence_ref'])
            if identity in document_ids:
                raise ValueError('Duplicate candidate document')
            document_ids.add(identity)
        _texts(row['unresolved'], 'unresolved conditions')
        result[slug] = deepcopy(row)
        identities.add(row['product_id'])
    return result


def build_dossiers(master, catalogue, copy_audit, image_audit, soyin, *, observed_at,
                   reply_review=None, reply_review_as_of=None):
    if (master['counts']['confirmed_fitments'] != 0 or master['counts']['director_validated'] != 0
            or image_audit['counts']['positive_commercial_image_permissions'] != 0):
        raise ValueError('Evidence has changed: review the conservative dossier policy before regenerating')
    live, copies, images = (_index(catalogue['items'], 'slug'), _index(copy_audit['products'], 'slug'),
                             _index(image_audit['articles'], 'slug'))
    proposals = _index(soyin['findings'], 'slug')
    tracker = {}
    for row in master['rows']:
        identity, slug = row['Identifiant produit'].split(' / ', 1)
        if slug in tracker:
            raise ValueError('Duplicate tracked article')
        tracker[slug] = (identity, row)
    if len(live) != 40 or set(live) != set(tracker) or set(live) != set(copies) or set(live) != set(images):
        raise ValueError('The four sources must cover the same 40 articles')
    # The trusted review clock is supplied separately, never taken from the
    # untrusted supplement or the (possibly historical) catalogue price date.
    reply_articles = (_validated_reply_review(reply_review, live, as_of=reply_review_as_of)
                      if reply_review is not None else {})
    dossiers = []
    for slug in sorted(live):
        p, c, image = live[slug], copies[slug], images[slug]
        identity, row = tracker[slug]
        if identity != p['id'] or c['id'] != identity:
            raise ValueError('Catalogue identity drift')
        proposal = proposals.get(slug)
        blockers = [
            {'owner': 'B_FOURNISSEUR', 'code': 'EXACT_SKU_VARIANT', 'action': 'Confirmer SKU retenu, finition, contenu et équivalence avec la pièce présentée.'},
            {'owner': 'B_FOURNISSEUR', 'code': 'FITMENT', 'action': row['Restrictions de montage']},
            {'owner': 'B_FOURNISSEUR', 'code': 'IMAGE_RIGHTS', 'action': 'Autorisation écrite couvrant les fichiers existants, leurs dérivés et les logos éventuels ; aucune nouvelle utilisation commerciale avant preuve.'},
            {'owner': 'B_FOURNISSEUR', 'code': 'COST_DELIVERY', 'action': 'Devis daté SKU/quantité/devise/MOQ, validité, poids/colis, port France, Incoterm, délai, retour et garantie.'},
            {'owner': 'C_ADMINISTRATEUR', 'code': 'AGENT_AND_TERMS', 'action': 'Désigner le responsable réel ; approuver fournisseur/SKU, régime fiscal, marge minimale et conditions légales, sans achat automatique.'},
            {'owner': 'A_CODEX', 'code': 'TECHNICAL_INTEGRATION', 'action': 'Raccorder les preuves reçues aux variantes/offres/tarifs/agents puis tester la chaîne ; aucune donnée inventée.'},
        ]
        if proposal and proposal['issues']:
            blockers.append({'owner': 'B_FOURNISSEUR', 'code': 'CANDIDATE_CONFLICT', 'action': '; '.join(proposal['issues'])})
        if image.get('image_rights_status') == 'REFUSED' or image.get('personalized_refusal_proof'):
            blockers.append({'owner': 'C_ADMINISTRATEUR', 'code': 'IMAGE_REFUSAL', 'action': 'Refus à respecter. Faire approuver une source autorisée ; protections SCP conservées, aucune image remplacée.'})
        dossiers.append({
            'product_id': identity, 'slug': slug, 'sku': p.get('sku'),
            'sku_status': 'OBSERVÉ_API' if p.get('sku') else 'NON_OBSERVÉ',
            'name': p['name'], 'category': row['Catégorie'],
            'supplier_selected': None, 'supplier_selected_confirmed': False,
            'supplier_candidates_evidence': row['Fournisseur'],
            'source_reference_candidates': row['Référence fournisseur'],
            'agent_responsible': None, 'exact_selected_variant': None,
            'candidate_soyin': proposal, 'alternative_verified': False,
            'compatibility_verified': False, 'restrictions_to_confirm': row['Restrictions de montage'],
            'title_description_review': c['assessment'], 'proposed_copy': c['local_copy'],
            'image_rights_status': image['image_rights_status'],
            'commercial_image_permission_confirmed': False, 'images_changed': False,
            'supplier_unit_cost_cents': None, 'supplier_currency': None,
            'sale_price_cents_observed': p['price_cents'], 'sale_currency_observed': p['currency'],
            'sale_price_observed_at': observed_at, 'sale_price_changed': False,
            'shipping_confirmed_cents': None, 'landed_cost_cents': None,
            'gross_margin_cents': None, 'net_margin_cents': None,
            'commercial_status': 'BLOQUÉ_PREUVES_MANQUANTES',
            'verification_statuses': {'supplier':'PENDING_SUPPLIER','hypersku':'PENDING_HYPERSKU',
                'compatibility':'PENDING_COMPATIBILITY','pricing':'PENDING_PRICING',
                'shipping':'PENDING_SHIPPING','image_rights':'PENDING_RIGHTS','director':'BLOCKED'},
            'publication_status': p['status'],
            'hypersku_mapping_confirmed': False,
            'hypersku_product_reference': None, 'hypersku_variant_reference': None,
            'catalogue_status_observed': p['status'], 'catalogue_verified_observed': p['is_verified'],
            'test_purchase_observed': p.get('test_purchase'),
            'pilot_rank': PILOTS.index(slug) + 1 if slug in PILOTS else None,
            'pilot_reason': PILOT_REASON if slug in PILOTS else None,
            'blockers': blockers,
            'sources': {
                'tracker': 'article-master-tracker.json#' + slug,
                'copy': 'catalogue/product-copy-audit.json#' + slug,
                'image': 'images/rights-and-fidelity-40.json#' + slug,
                'supplier': 'continuation/soyin-29-review.json#' + slug if proposal else row['Lien produit fournisseur'],
                'fitment': row['Preuve de compatibilité'],
                'source_tracker_recorded_at': master['recorded_at'],
                'image_audit_at': image_audit.get('checked_at'),
            },
            'next_action': 'Traiter en priorité les preuves de ce candidat pilote.' if slug in PILOTS else 'Attendre la clôture des 5 pilotes, conserver les restrictions existantes.',
        })
        if slug in reply_articles:
            reply = reply_articles[slug]
            dossiers[-1]['candidate_supplier_replies'] = [deepcopy(reply)]
            dossiers[-1]['sources']['supplier_reply_review'] = {
                'recorded_at': reply_review['recorded_at'],
                'checked_as_of': reply_review_as_of,
                'scope': reply_review['scope'],
                'evidence_refs': [source['evidence_ref'] for source in reply['sources']],
            }
            dossiers[-1]['next_action'] = reply['next_action']
    count = Counter(b['owner'] for d in dossiers for b in d['blockers'])
    fingerprint_sources = [master, catalogue, copy_audit, image_audit, soyin]
    if reply_review is not None:
        fingerprint_sources.append({'reply_review': reply_review, 'reply_review_as_of': reply_review_as_of})
    fingerprint = sha256(json.dumps(fingerprint_sources,
                                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    result = {'observed_at': observed_at, 'source_digest_sha256': fingerprint,
            'scope': 'Projection privée sur preuves disponibles ; pas une nouvelle confirmation fournisseur.',
            'counts': {'articles': 40, 'pilot_candidates': 5, 'fully_verified': 0, 'commercially_blocked': 40,
                       'selected_suppliers_confirmed': 0, 'fitments_confirmed': 0, 'supplier_prices_confirmed': 0,
                       'france_shipping_confirmed': 0, 'margins_calculable': 0,
                       'hypersku_mappings_confirmed': 0,
                       'pending_by_dimension': {'PENDING_SUPPLIER':40,'PENDING_HYPERSKU':40,
                           'PENDING_COMPATIBILITY':40,'PENDING_PRICING':40,'PENDING_SHIPPING':40,'PENDING_RIGHTS':40},
                       'candidate_soyin_named_skus': sum(bool((x.get('source_values') or {}).get('supplier_sku')) for x in proposals.values()),
                       'blockers_by_owner': dict(count)}, 'articles': dossiers}
    if reply_review is not None:
        result['counts']['candidate_reply_articles'] = len(reply_articles)
        result['counts']['documents_unreadable'] = sum(len(row['documents']) for row in reply_articles.values())
    # Outputs must not alias historical evidence, even without the optional review.
    return deepcopy(result)
