"""Evidence-only commercial dossiers; candidates are NEVER selected suppliers.

This is a private reporting projection, not a catalogue import or approval tool.
Missing confirmed costs stay null. Historical source timestamps are preserved.
"""
from collections import Counter
from hashlib import sha256
import json

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


def build_dossiers(master, catalogue, copy_audit, image_audit, soyin, *, observed_at):
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
    count = Counter(b['owner'] for d in dossiers for b in d['blockers'])
    fingerprint = sha256(json.dumps([master, catalogue, copy_audit, image_audit, soyin],
                                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'observed_at': observed_at, 'source_digest_sha256': fingerprint,
            'scope': 'Projection privée sur preuves disponibles ; pas une nouvelle confirmation fournisseur.',
            'counts': {'articles': 40, 'pilot_candidates': 5, 'fully_verified': 0, 'commercially_blocked': 40,
                       'selected_suppliers_confirmed': 0, 'fitments_confirmed': 0, 'supplier_prices_confirmed': 0,
                       'france_shipping_confirmed': 0, 'margins_calculable': 0,
                       'candidate_soyin_named_skus': sum(bool((x.get('source_values') or {}).get('supplier_sku')) for x in proposals.values()),
                       'blockers_by_owner': dict(count)}, 'articles': dossiers}
