"""One real provider self-send, to EMAIL_FROM only; never logs credentials or body."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env')
from app.config import get_settings
from app.services.email_service import EmailService
from app.services.email_templates import EmailContent, _layout

def main():
    config = get_settings()
    if not config.email_enabled:
        print('BLOQUÉ : EMAIL_ENABLED=false ; aucun email envoyé.')
        return 2
    try: config.validate()
    except (RuntimeError, ValueError) as error:
        print('BLOQUÉ : configuration incomplète ou invalide : '+str(error))
        return 2
    html, text = _layout('Vérification email TYMotors', ['Test technique de livraison. Aucun achat ni inscription.'])
    service = EmailService(config, None)
    try:
        message_id = service.transport(config.email_from_address, EmailContent('TYMotors — test de livraison', html, text))
    except Exception as error:
        print('ÉCHEC fournisseur : '+type(error).__name__+'. Vérifier les journaux du fournisseur ; aucune clé affichée.')
        return 1
    print('ACCEPTÉ par le fournisseur'+(' (identifiant présent)' if message_id else '')+'. Vérifier la réception/spam et SPF/DKIM/DMARC : acceptation ne prouve pas réception.')
    return 0

if __name__ == '__main__': sys.exit(main())
