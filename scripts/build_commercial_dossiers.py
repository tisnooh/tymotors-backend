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

from app.commerce_dossiers import build_dossiers

URL = 'https://tymotors-backend-eu.onrender.com/api/products?preview=true&limit=100'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
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
                            read('continuation/soyin-29-review.json'), observed_at=observed_at)
    args.output.mkdir(parents=True)
    (args.output / 'dossiers-40.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    md = ['# TYMotors — 40 dossiers et 5 candidats pilotes', '',
          'Aucun produit commercialement validé. Aucune photo, prix public ou donnée de production modifiée.', '',
          'Date des prix observés : ' + observed_at, '',
          '| Pilote | Produit | SKU proposé Soyin (NON retenu) | Manques bloquants |',
          '|---|---|---|---|']
    for item in sorted((x for x in result['articles'] if x['pilot_rank']), key=lambda x: x['pilot_rank']):
        candidate_sku = ((item.get('candidate_soyin') or {}).get('source_values') or {}).get('supplier_sku') or 'NON CONFIRMÉ / MANQUANT'
        md.append(f"| {item['pilot_rank']} | {item['name']} | {candidate_sku} | Variante/finition, montage, droits, devis, port France, agent, garantie |")
    for item in result['articles']:
        md += ['', '## ' + item['name'], '', f"Identifiant : {item['product_id']} — SKU catalogue : {item['sku'] or 'non observé'}", '',
               f"Prix observé : {item['sale_price_cents_observed']} centimes {item['sale_currency_observed']} ; coût et marge : non calculables.", '',
               'Fournisseurs candidats (aucun retenu confirmé) : ' + item['supplier_candidates_evidence'], '',
               'Droits : ' + item['image_rights_status'] + ' ; images conservées, aucune nouvelle utilisation autorisée.', '',
               'Source : ' + item['sources']['tracker'], '']
        md += [f"- {b['owner']} — {b['code']} : {b['action']}" for b in item['blockers']]
    (args.output / 'DOSSIERS.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(json.dumps({'counts': result['counts'], 'output': str(args.output), 'catalogue_mutated': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
