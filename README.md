# Cafe Fundraiser Telegram Preorder Bot

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Copy `.env.example` to `.env` and fill in the token, admin Telegram user ID, and fundraiser group ID.
3. Put the menu image at `assets/menu.png` and payment QR image at `assets/payment_qr.png`.
4. Edit `menu.json` with your categories and items. Set `available` to `false` for sold-out items.
5. Install dependencies and run:

```text
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

The bot must be added to the fundraiser group and allowed to send messages. Customers must start a private chat with the bot before ordering. The bot does not parse collection dates; it stores and forwards the customer’s text exactly as entered.

## Updating the menu

Edit `menu.json`, save it, then send `/reload_menu` to the bot as the configured admin. Changes apply to new orders immediately. Existing submitted orders keep their original item data.

## Finding IDs

Use a Telegram ID bot to find your personal user ID. To find the group ID, add the bot to the group, send a message, and inspect the bot update logs or use a Telegram ID utility. Group IDs normally start with `-100`.

## Important production notes

Keep `.env`, the SQLite database, and payment images private. Back up `data/orders.sqlite3`. For production hosting, run this on a small always-on server or container with persistent storage.
