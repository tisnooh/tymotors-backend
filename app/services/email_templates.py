from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class EmailContent:
    subject: str
    html: str
    text: str


def _button(label: str, url: str) -> str:
    return (
        f'<a href="{escape(url, quote=True)}" style="display:inline-block;background:#e10600;color:#fff;'
        'font:700 13px Arial,sans-serif;letter-spacing:1.6px;text-decoration:none;padding:15px 22px;'
        f'border-radius:4px">{escape(label)}</a>'
    )


def _layout(title: str, body_html: str, body_text: str, *, footer_html: str = "") -> tuple[str, str]:
    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;background:#050608;color:#fff;font-family:Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#050608"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#0d1015;border:1px solid #242936">
<tr><td style="padding:28px 30px;border-bottom:2px solid #e10600;font:700 22px Arial,sans-serif;letter-spacing:5px">TY<span style="color:#f2c94c">MOTORS</span></td></tr>
<tr><td style="padding:34px 30px"><h1 style="margin:0 0 20px;font:700 30px/1.2 Arial,sans-serif;color:#fff">{escape(title)}</h1>{body_html}</td></tr>
<tr><td style="padding:22px 30px;border-top:1px solid #242936;color:#8e94a3;font:12px/1.6 Arial,sans-serif">TYMotors · Pièces et accessoires automobiles.{footer_html}</td></tr>
</table></td></tr></table></body></html>"""
    return html, f"TYMOTORS\n\n{title}\n\n{body_text}\n\nTYMotors · Pièces et accessoires automobiles."


def welcome(first_name: str | None, account_url: str) -> EmailContent:
    name = escape((first_name or "").strip())
    greeting = f"Bienvenue {name}," if name else "Bienvenue,"
    body = (
        f'<p style="color:#d5d8df;font:16px/1.7 Arial,sans-serif">{greeting}</p>'
        '<p style="color:#d5d8df;font:16px/1.7 Arial,sans-serif">Votre compte TYMotors est maintenant actif.</p>'
        '<p style="color:#d5d8df;font:16px/1.7 Arial,sans-serif">Retrouvez vos commandes, véhicules, favoris et informations personnelles.</p>'
        f'<p style="margin:28px 0 0">{_button("ACCÉDER À MON COMPTE", account_url)}</p>'
    )
    html, text = _layout("Bienvenue chez TYMotors", body, f"{greeting}\nVotre compte TYMotors est maintenant actif.\n\nAccéder à mon compte : {account_url}")
    return EmailContent("Bienvenue chez TYMotors", html, text)


def newsletter_confirmation(confirm_url: str) -> EmailContent:
    body = (
        '<p style="color:#d5d8df;font:16px/1.7 Arial,sans-serif">Une dernière étape.</p>'
        '<p style="color:#d5d8df;font:16px/1.7 Arial,sans-serif">Confirmez votre inscription pour recevoir nos nouveautés, produits, sélections automobiles et offres.</p>'
        f'<p style="margin:28px 0">{_button("CONFIRMER MON INSCRIPTION", confirm_url)}</p>'
        '<p style="color:#8e94a3;font:13px/1.6 Arial,sans-serif">Si vous n’avez pas demandé cette inscription, ignorez cet email.</p>'
    )
    html, text = _layout("Confirmez votre inscription", body, f"Confirmez votre inscription TYMotors : {confirm_url}\n\nSi vous ne l’avez pas demandée, ignorez cet email.")
    return EmailContent("Confirmez votre inscription à TYMotors", html, text)


def _money(cents: int, currency: str) -> str:
    return f"{cents / 100:,.2f} {currency}".replace(",", " ").replace(".", ",")


def _order_summary(order: dict[str, Any], items: list[dict[str, Any]]) -> tuple[str, str]:
    html_rows, text_rows = [], []
    for item in items:
        name = escape(str(item.get("product_name") or "Produit"))
        quantity = int(item.get("quantity") or 1)
        price = _money(int(item.get("unit_amount_cents") or 0) * quantity, order.get("currency", "EUR"))
        vehicle = item.get("selected_vehicle") or {}
        vehicle_text = " ".join(str(vehicle.get(k) or "") for k in ("brand_slug", "model", "generation", "year")).strip()
        sku = escape(str(item.get("sku") or ""))
        extra = f'<br><span style="color:#8e94a3;font-size:12px">{sku}{" · " if sku and vehicle_text else ""}{escape(vehicle_text)}</span>' if sku or vehicle_text else ""
        image_url = str(item.get("image_url") or "")
        parsed = urlparse(image_url)
        image = f'<img src="{escape(image_url, quote=True)}" width="58" height="58" alt="" style="display:block;width:58px;height:58px;object-fit:cover;border-radius:5px">' if parsed.scheme == "https" and parsed.hostname else ""
        html_rows.append(f'<tr><td width="68" style="padding:10px 10px 10px 0">{image}</td><td style="padding:10px 0;color:#fff">{name}{extra} × {quantity}</td><td align="right" style="color:#fff">{price}</td></tr>')
        text_rows.append(f"- {item.get('product_name') or 'Produit'} ({item.get('sku') or 'sans variante'}) × {quantity} — {price}" + (f" — {vehicle_text}" if vehicle_text else ""))
    currency = order.get("currency", "EUR")
    totals = [
        ("Sous-total", int(order.get("subtotal_cents") or 0)),
        ("Livraison", int(order.get("shipping_amount_cents") or 0)),
        ("Taxes", int(order.get("tax_amount_cents") or 0)),
        ("Total", int(order.get("total_cents") or 0)),
    ]
    total_rows = "".join(f'<tr><td colspan="2" style="padding-top:8px;color:{"#f2c94c" if label == "Total" else "#aeb3bf"};font-weight:{"bold" if label == "Total" else "normal"}">{label}</td><td align="right" style="padding-top:8px;color:{"#f2c94c" if label == "Total" else "#fff"};font-weight:{"bold" if label == "Total" else "normal"}">{_money(cents, currency)}</td></tr>' for label, cents in totals)
    table = '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:20px 0;border-top:1px solid #303541">' + "".join(html_rows) + total_rows + '</table>'
    return table, "\n".join(text_rows) + "\n" + "\n".join(f"{label} : {_money(cents, currency)}" for label, cents in totals)


def order_event(kind: str, order: dict[str, Any], items: list[dict[str, Any]], order_url: str, *, amount_cents: int | None = None) -> EmailContent:
    number = str(order.get("order_number") or "")
    titles = {
        "order_confirmation": (f"Commande TYMotors #{number}", "Commande enregistrée"),
        "payment_confirmed": (f"Paiement confirmé — commande #{number}", "Paiement confirmé"),
        "order_processing": ("Votre commande TYMotors est en préparation", "Commande en préparation"),
        "order_shipped": ("Votre commande TYMotors est en route", "Commande expédiée"),
        "order_delivered": ("Votre commande TYMotors a été livrée", "Commande livrée"),
        "order_cancelled": (f"Commande #{number} annulée", "Commande annulée"),
        "refund_confirmed": ("Remboursement TYMotors confirmé", "Remboursement confirmé"),
    }
    subject, title = titles[kind]
    summary_html, summary_text = _order_summary(order, items)
    intro = {
        "order_confirmation": "Merci. Votre commande a bien été enregistrée.",
        "payment_confirmed": "Votre paiement a été confirmé de manière sécurisée.",
        "order_processing": "Notre équipe prépare actuellement votre commande.",
        "order_shipped": "Votre commande a quitté nos locaux.",
        "order_delivered": "Votre commande est indiquée comme livrée.",
        "order_cancelled": "Votre commande a été annulée.",
        "refund_confirmed": "Stripe a confirmé votre remboursement. Son apparition sur votre compte dépend ensuite du délai de votre banque.",
    }[kind]
    details = ""
    details_text = ""
    if kind == "order_shipped":
        carrier = escape(str(order.get("carrier") or "Transporteur"))
        tracking = escape(str(order.get("tracking_number") or ""))
        details = f'<p style="color:#d5d8df">{carrier} · N° {tracking}</p>'
        details_text = f"\n{carrier} · N° {tracking}"
    if kind == "refund_confirmed" and amount_cents is not None:
        amount = _money(amount_cents, order.get("currency", "EUR"))
        details = f'<p style="color:#f2c94c;font-weight:bold">Montant remboursé : {amount}</p>'
        details_text = f"\nMontant remboursé : {amount}"
    if kind == "order_confirmation":
        address = order.get("shipping_address") or {}
        lines = [address.get("line1"), address.get("line2"), " ".join(filter(None, [address.get("postal_code"), address.get("city")])), address.get("country")]
        lines = [escape(str(line)) for line in lines if line]
        if lines:
            details += f'<p style="color:#aeb3bf;font:14px/1.6 Arial,sans-serif"><strong style="color:#fff">Adresse de livraison</strong><br>{"<br>".join(lines)}</p>'
            details_text += "\nAdresse de livraison : " + ", ".join(lines)
    if kind == "order_cancelled" and order.get("payment_status") == "paid":
        details += '<p style="color:#aeb3bf;font:14px/1.6 Arial,sans-serif">Si un paiement a été encaissé, le remboursement est confirmé séparément après validation par Stripe.</p>'
        details_text += "\nTout remboursement éventuel sera confirmé séparément après validation par Stripe."
    action_url = order.get("tracking_url") if kind == "order_shipped" and order.get("tracking_url") else order_url
    action_label = "SUIVRE MA COMMANDE" if kind == "order_shipped" else "VOIR MA COMMANDE"
    body = f'<p style="color:#d5d8df;font:16px/1.7 Arial,sans-serif">Commande #{escape(number)}</p><p style="color:#d5d8df;font:16px/1.7 Arial,sans-serif">{escape(intro)}</p>{details}{summary_html}<p style="margin:28px 0 0">{_button(action_label, action_url)}</p>'
    html, text = _layout(title, body, f"Commande #{number}\n{intro}{details_text}\n\n{summary_text}\n\n{action_label} : {action_url}")
    return EmailContent(subject, html, text)
