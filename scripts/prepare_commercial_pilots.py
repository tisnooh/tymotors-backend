"""Prepare five private pilot packets from existing files. No API/import/mail.

The output directory must be new. The generated JSON is an administrative
review packet, NOT a supplier/provider upload format or an executable import.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from app.commerce_pilot_preparation import prepare_pilot_catalogue
from scripts.build_commercial_dossiers import _md


def render_pilot_preparation(result):
    lines = ['# TYMotors — cinq fiches pilotes préparées localement', '',
             'Préparation datée : ' + _md(result['prepared_at']),
             'Observation historique du catalogue : ' + _md(result['source_observed_at']), '',
             'Aucun import, achat, message fournisseur, changement de prix public, image, design ou publication.',
             'Les déclarations Soyin restent celles de candidats non sélectionnés. Aucun montage réel validé.',
             'L’examen des photographies reste différé par le propriétaire ; il ne constitue pas une autorisation nouvelle.', '',
             '| Rang | Article | SKU candidat Soyin | Référence retenue | Préparation |',
             '|---|---|---|---|---|']
    for pilot in result['pilots']:
        lines.append('| ' + str(pilot['pilot_rank']) + ' | ' + _md(pilot['catalogue_copy']['title'])
                     + ' | ' + _md(pilot['supplier_choice']['candidate_reference'])
                     + ' | NON CONFIRMÉE | Variante draft ; offre/transport incomplets |')
    for pilot in result['pilots']:
        copy, candidate = pilot['catalogue_copy'], pilot['candidate_declarations']
        lines += ['', '## ' + _md(copy['title']), '',
                  'UUID : ' + _md(pilot['product_id']) + ' — slug : ' + _md(pilot['slug']),
                  'SKU interne observé : ' + _md(pilot['internal_catalogue_sku']), '',
                  '### Texte conservé sans réécriture', '', _md(copy['subtitle']), '', _md(copy['description']), '',
                  '### Déclarations candidates, pas caractéristiques validées du produit', '',
                  '- Matière déclarée : ' + _md(candidate['material']['value']) + ' — ' + _md(candidate['material']['evidence_ref']),
                  '- Montage déclaré : ' + _md(candidate['fitment_text']['value']) + ' — ' + _md(candidate['fitment_text']['evidence_ref']),
                  '- Référence : ' + _md(candidate['reference_evidence']),
                  '- Réponse reçue le ' + _md(candidate['reply_received_at']) + ' ; message ' + _md(candidate['source_message_id']), '',
                  '### Montage restant à préciser', '']
        lines += ['- ' + _md(value) for value in pilot['actual_product_fitment']['restrictions_to_confirm']]
        lines += ['- Extension NON PROUVÉE, pas incompatibilité attestée : ' + _md(value)
                  for value in pilot['actual_product_fitment']['extensions_not_proved']]
        lines += ['', '### Données d’import privées', '',
                  '- VariantInput : schéma valide en draft uniquement, stock de garde 0, is_verified=false, aucune compatibilité associée.',
                  '- Prix : instantané existant recopié sans changement, non réapprouvé et non écrit dans le catalogue.',
                  '- OfferInput INCOMPLET / NON IMPORTABLE : ' + ', '.join(_md(value) for value in pilot['candidate_offer_template']['missing_or_invalid_fields']),
                  '- ShippingRateInput INCOMPLET / NON IMPORTABLE : ' + ', '.join(_md(value) for value in pilot['direct_france_shipping_template']['missing_or_invalid_fields']),
                  '- Vérifier les variantes/SKU existants avant tout import ultérieur autorisé ; aucun UUID fournisseur ou variante inventé.', '',
                  '### Manques commerciaux', '']
        lines += ['- ' + _md(value) for value in pilot['missing_fields']['commercial']]
    lines += ['', '## Limites', '',
              'Le stock 0 protège le brouillon ; il ne décrit pas le stock fournisseur. Les coûts/taxes/port inconnus restent null, pas zéro.',
              'Aucune référence retenue, marge, compatibilité, transporteur ou disponibilité n’est déduite de cette préparation.',
              'Le fichier JSON n’est pas un import fournisseur/HyperSKU certifié. Aucun envoi externe n’est effectué.']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dossiers', type=Path, required=True)
    parser.add_argument('--soyin', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be a new directory; historical evidence is never overwritten')
    dossier_bytes, soyin_bytes = args.dossiers.read_bytes(), args.soyin.read_bytes()
    result = prepare_pilot_catalogue(json.loads(dossier_bytes), json.loads(soyin_bytes),
                                     prepared_at=datetime.now(timezone.utc).isoformat(),
                                     dossier_label=str(args.dossiers), soyin_label=str(args.soyin))
    result['sources']['input_file_sha256'] = {'dossiers': sha256(dossier_bytes).hexdigest(),
                                             'soyin_review': sha256(soyin_bytes).hexdigest()}
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    markdown = render_pilot_preparation(result)
    args.output.mkdir(parents=True)
    (args.output / 'pilots-5.json').write_text(encoded, encoding='utf-8')
    (args.output / 'PILOTS.md').write_text(markdown, encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'summary': result['summary'],
                      'imports_executed': 0, 'catalogue_mutated': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
