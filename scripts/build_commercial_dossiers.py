"""Generate private JSON/Markdown dossiers. Never writes catalogue/DB/images.

python -m scripts.build_commercial_dossiers --source <review-dir> --output <new-dir> --live
The explicit --live switch performs ONE read-only request to the known public API.
Otherwise historical public prices are dated as historical, never called current.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import urlopen

from app.commerce_dossiers import build_dossiers,apply_owner_execution_scope

URL = 'https://tymotors-backend-eu.onrender.com/api/products?preview=true&limit=100'


def _md(value):
    """Display supplier text as text, not active HTML or Markdown instructions."""
    text = str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = text.replace('\r', ' ').replace('\n', ' ')
    for character in ('\\', '`', '*', '_', '[', ']', '|', '#', '!'):
        text = text.replace(character, '\\' + character)
    return text


def render_markdown(result):
    md = ['# TYMotors — 40 dossiers et 5 candidats pilotes', '',
          'Aucun produit commercialement validé. Aucune photo, prix public ou donnée de production modifiée.', '',
          'Date des prix observés : ' + result['observed_at'], '',
          '| Pilote | Produit | SKU proposé Soyin (NON retenu) | Manques bloquants |',
          '|---|---|---|---|']
    deferred=result.get('execution_policy',{}).get('photo_review')=='DEFERRED_BY_OWNER'
    if deferred:
        md[2]='Trois fournisseurs initiaux uniquement : Tianzhiyu, Soyintech/Soyin, GZTM/Leju. Étape de certification photo écartée du travail prioritaire ; images inchangées. Aucune validation commerciale inventée.'
    for item in sorted((x for x in result['articles'] if x['pilot_rank']), key=lambda x: x['pilot_rank']):
        candidate_sku = ((item.get('candidate_soyin') or {}).get('source_values') or {}).get('supplier_sku') or 'NON CONFIRMÉ / MANQUANT'
        missing='Variante/finition, montage, devis, port France, agent, garantie' if deferred else 'Variante/finition, montage, droits, devis, port France, agent, garantie'
        md.append(f"| {item['pilot_rank']} | {item['name']} | {candidate_sku} | {missing} |")
    for item in result['articles']:
        md += ['', '## ' + item['name'], '', f"Identifiant : {item['product_id']} — SKU catalogue : {item['sku'] or 'non observé'}", '',
               f"Prix observé : {item['sale_price_cents_observed']} centimes {item['sale_currency_observed']} ; coût et marge : non calculables.", '',
               'Fournisseurs candidats (aucun retenu confirmé) : ' + item['supplier_candidates_evidence'], '',
               ('Photos : étape de certification différée par le propriétaire ; fichiers inchangés.' if deferred else
                'Droits : ' + item['image_rights_status'] + ' ; images conservées, aucune nouvelle utilisation autorisée.'), '',
               'Publication séparée : ' + item['publication_status'] + ' ; blocages simultanés : ' + ', '.join(item['verification_statuses'].values()), '',
               'Source : ' + item['sources']['tracker'], '',
               'Prochaine action : '+item['next_action'], '']
        md += [f"- {b['owner']} — {b['code']} : {b['action']}" for b in item['blockers']]
        for reply in item.get('candidate_supplier_replies', []):
            review_source = item['sources']['supplier_reply_review']
            md += ['', '### Réponse candidat — NON VALIDÉE POUR LE PRODUIT TYMOTORS', '',
                   'Analyse datée : ' + _md(review_source['recorded_at']),
                   'Horloge explicite de contrôle des réponses : ' + _md(review_source['checked_as_of']),
                   'Fournisseur candidat : ' + _md(reply['supplier_name']) + ' ; référence proposée : '
                   + _md(reply['candidate_reference'] or 'NON CONFIRMÉE') + ' ; statut : RESPONSE_INCOMPLETE.', '',
                   'Ces déclarations ne sélectionnent aucun fournisseur et ne confirment ni le montage, ni les droits, ni le prix du produit TYMotors.',
                   'Une déclaration générale d’expédition ne constitue ni un coût unitaire ni un devis de port vers la France.', '']
            for source in reply['sources']:
                md.append('- Message reçu le ' + _md(source['received_at']) + ' : ' + _md(source['evidence_ref']))
            for fact in reply['confirmed_candidate_facts']:
                md.append('- Déclaration [' + _md(fact['scope']) + '] ' + _md(fact['fact']) + ' : '
                          + _md(fact['value']) + ' — preuves : ' + ', '.join(_md(ref) for ref in fact['evidence_refs']))
            for document in reply['documents']:
                md += ['- Document INCOMPLET / ILLISIBLE — ' + _md(document['filename']) + ' ; '
                       + str(document['bytes']) + ' octets ; SHA-256 : ' + _md(document['sha256'])
                       + ' ; preuve : ' + _md(document['evidence_ref']) + '. Aucune caractéristique déduite de ce document.',
                       '  Contrôles : ' + '; '.join(_md(check) for check in document['checks'])]
            md += ['- Non résolu : ' + _md(value) for value in reply['unresolved']]
            md += ['- Action ciblée : ' + _md(reply['next_action'])]
    return '\n'.join(md) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--historical-scope',action='store_true',
                        help='Reproduce the former private workflow; current default uses the owner three-supplier scope')
    parser.add_argument('--reply-review', type=Path,
                        help='Optional closed-schema candidate reply evidence; never an approval or price import')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be a new directory; evidence is never overwritten')
    def read(relative):
        return json.loads((args.source / relative).read_text(encoding='utf-8'))
    if args.live:
        with urlopen(URL, timeout=45) as response:
            catalogue = json.load(response)
        observed_at = datetime.now(timezone.utc).isoformat()
    else:
        catalogue = read('catalogue/live-copy-snapshot.json')
        observed_at = catalogue['recorded_at']
    # Only selected public fields: no image download or derivative generation.
    catalogue = {'items': [{k: item.get(k) for k in ('id','slug','sku','name','price_cents','currency',
                                                   'status','is_verified','test_purchase')}
                           for item in catalogue['items']]}
    result = build_dossiers(read('article-master-tracker.json'), catalogue,
                            read('catalogue/product-copy-audit.json'), read('images/rights-and-fidelity-40.json'),
                            read('continuation/soyin-29-review.json'), observed_at=observed_at,
                            reply_review=json.loads(args.reply_review.read_text(encoding='utf-8')) if args.reply_review else None,
                            reply_review_as_of=datetime.now(timezone.utc).isoformat() if args.reply_review else None)
    if not args.historical_scope:
        result=apply_owner_execution_scope(result)
    args.output.mkdir(parents=True)
    (args.output / 'dossiers-40.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.output / 'DOSSIERS.md').write_text(render_markdown(result), encoding='utf-8')
    print(json.dumps({'counts': result['counts'], 'output': str(args.output), 'catalogue_mutated': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
