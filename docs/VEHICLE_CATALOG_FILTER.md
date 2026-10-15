# Catalogue personnalisé — 16 octobre 2026

`GET /api/products?strict_vehicle=true` exige une marque, un modèle et un châssis/génération précis. Seuls les produits vérifiés avec **une même règle de compatibilité vérifiée** correspondant à ces trois critères peuvent être suggérés. Les détails fournis (année, carrosserie, finition, caméra et capteurs) doivent aussi respecter cette règle. Les champs inconnus ne deviennent pas des options positives ni une confirmation de montage.

Le filtrage intervient avant le comptage et la pagination. La réponse porte `fitment_scope: "verified_vehicle"` ; le configurateur refuse une réponse d'une ancienne API qui ignorerait ce nouveau paramètre. Les brouillons sans règles détaillées ne contournent plus cette sélection. Aucun rapprochement par nom de produit, stock ou compatibilité n'a été inventé.

Sans cette option, la boutique générale et les aperçus de démonstration conservent leur comportement. Les contrôles de compatibilité, de disponibilité et de panier existants restent nécessaires et inchangés ; cette liste n'autorise pas un achat.

Tests : `tests/test_vehicle_catalog.py` couvre W177/W205, données absentes/non vérifiées, règles croisées, génération seule, critères contradictoires, options inconnues, validation de requête et pagination après filtrage. Suite backend complète : 286 tests réussis, sans écriture distante.
