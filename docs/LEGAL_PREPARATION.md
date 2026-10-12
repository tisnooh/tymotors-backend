# Préparation légale — avant toute vente réelle

La configuration publique `/api/site-config` est une liste explicite de champs non secrets. Les pages mentions, CGV, confidentialité et rétractation lisent `LEGAL_*` depuis le backend. Toute absence apparaît « à renseigner » avec un avertissement. Pour une EI, utiliser l’identité légale du propriétaire et la forme EI, pas seulement le nom commercial. Aucun numéro ou statut TVA n’est présumé.

Renseigner toutes les variables `LEGAL_*` dans `.env.example`, vérifier les coordonnées des hébergeurs, choisir réellement un médiateur et confirmer l’adresse de retour. Faire vérifier les CGV (garanties, exceptions, livraison, équipements routiers), les transferts hors EEE et les durées de conservation. Prévoir une procédure effective de suppression/archivage : aucune purge automatique n’est annoncée comme réalisée.

Rétractation : `/legal/withdrawal` (également `/support/returns`) nécessite numéro, email et confirmation explicite. La demande est enregistrée dans `contact_messages`; l’accusé est téléchargeable et envoyé par le service email configuré. Un échec email n’annule pas la demande et n’est pas présenté comme une livraison réussie. Aucun remboursement automatique. Migration `withdrawal_receipts` requise pour le type d’email.

L’export admin `/api/admin/orders/{id}/document` protège le récapitulatif et emploie les mêmes champs légaux. **Il ne s’agit pas d’une facture fiscale** et il est étiqueté ainsi. Factures définitives : action manuelle requise avant live, choisir une solution conforme avec numérotation chronologique immuable, détail TVA adapté au statut réel, avoirs et archivage. Renseigner un SIRET ne transforme pas cet export en facture valide.

Sources vérifiées le 12 octobre 2026 :

- [Mentions EI](https://entreprendre.service-public.gouv.fr/vosdroits/F31228)
- [Commerce en ligne](https://entreprendre.service-public.gouv.fr/vosdroits/F23455)
- [Rétractation](https://www.service-public.gouv.fr/particuliers/vosdroits/F10485)
- [Conformité](https://www.service-public.gouv.fr/particuliers/vosdroits/F11094)
- [Information clients CNIL](https://www.cnil.fr/fr/exemple-dinformation-clients-dun-site-de-vente-en-ligne-prospection-par-courriel-et-transmission-de)
- [Mentions facture EI](https://www.service-public.gouv.fr/entreprendre/vosdroits/F31808?profil=entrepreneur-individuel)
