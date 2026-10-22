import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)


load_dotenv()

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)

log = logging.getLogger(__name__)

BASE = Path(__file__).parent

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_USER_ID"])
GROUP_ID = int(os.environ["FUNDRAISER_GROUP_ID"])

MENU_PATH = BASE / os.getenv("MENU_PATH", "menu.json")
DB_PATH = BASE / os.getenv("DATABASE_PATH", "data/orders.sqlite3")
QR_PATH = BASE / os.getenv("PAYMENT_QR_PATH", "assets/payment_qr.png")
MENU_IMAGE_PATH = BASE / os.getenv("MENU_IMAGE_PATH", "assets/menu.png")

CHOOSING, REMARKS, TAKEAWAY, COLLECTION, PAYMENT = range(5)


def load_menu():
    with MENU_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def item_index():
    result = {}

    for category in load_menu().get("categories", []):
        for item in category.get("items", []):
            result[item["id"]] = (category["id"], item)

    return result


def get_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            username TEXT,
            order_json TEXT NOT NULL,
            remarks TEXT,
            takeaway INTEGER NOT NULL DEFAULT 0,
            collection_time TEXT,
            payment_file_id TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    connection.commit()
    return connection


def money(value):
    return f"${value:.2f}"


def main_keyboard():
    return ReplyKeyboardMarkup(
        [["🛒 Order", "📋 Show menu"]],
        resize_keyboard=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "Welcome! 👋 Use the buttons below to view the menu or place a preorder. \n\nPlease note that desserts are only available from 10pm-12am. ",
        reply_markup=main_keyboard(),
    )

    return ConversationHandler.END


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if MENU_IMAGE_PATH.exists():
        with MENU_IMAGE_PATH.open("rb") as menu_image:
            await update.message.reply_photo(menu_image)
    else:
        await update.message.reply_text(
            "The menu image has not been uploaded yet."
        )


def category_markup():
    rows = []

    for category in load_menu().get("categories", []):
        has_available_items = any(
            item.get("available", True)
            for item in category.get("items", [])
        )

        if has_available_items:
            rows.append(
                [
                    InlineKeyboardButton(
                        category["name"],
                        callback_data=f"cat:{category['id']}",
                    )
                ]
            )

    rows.append(
        [
            InlineKeyboardButton(
                "✅ Review order",
                callback_data="review",
            )
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="cancel",
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


async def begin_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cart"] = []

    await update.message.reply_text(
        "Choose a category, then tap items to add them:",
        reply_markup=category_markup(),
    )

    return CHOOSING


async def category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category_id = query.data.split(":", 1)[1]

    menu_category = next(
        category
        for category in load_menu()["categories"]
        if category["id"] == category_id
    )

    buttons = []

    for item in menu_category.get("items", []):
        if item.get("available", True):
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"{item['name']} — {money(item['price'])}",
                        callback_data=f"add:{item['id']}",
                    )
                ]
            )

    buttons.append(
        [
            InlineKeyboardButton(
                "⬅️ Categories",
                callback_data="categories",
            )
        ]
    )

    await query.edit_message_text(
        menu_category["name"],
        reply_markup=InlineKeyboardMarkup(buttons),
    )

    return CHOOSING


async def add_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    item_id = query.data.split(":", 1)[1]
    index = item_index()

    if item_id not in index:
        await query.answer(
            "That item is no longer available.",
            show_alert=True,
        )
        return CHOOSING

    item = index[item_id][1]

    if not item.get("available", True):
        await query.answer(
            "Sorry, that item is sold out.",
            show_alert=True,
        )
        return CHOOSING

    await query.answer("Added")

    cart = context.user_data.setdefault("cart", [])

    for entry in cart:
        if entry["item_id"] == item_id:
            entry["quantity"] += 1
            break
    else:
        cart.append(
            {
                "item_id": item_id,
                "quantity": 1,
            }
        )

    await query.edit_message_text(
        "Added! Choose another item or review your order.",
        reply_markup=category_markup(),
    )

    return CHOOSING


def order_text(cart, takeaway=False):
    index = item_index()
    total = 0
    lines = []

    for entry in cart:
        item = index[entry["item_id"]][1]
        quantity = entry["quantity"]
        subtotal = item["price"] * quantity

        total += subtotal

        lines.append(
            f"• {quantity} × {item['name']} — {money(subtotal)}"
        )

    if takeaway:
        total += 0.20
        lines.append("• Takeaway charge — $0.20")

    return "\n".join(lines) + f"\n\nTotal: {money(total)}"


async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "Choose a category:",
        reply_markup=category_markup(),
    )

    return CHOOSING


async def review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    cart = context.user_data.get("cart", [])

    if not cart:
        await query.edit_message_text(
            "Your order is empty. Choose an item first.",
            reply_markup=category_markup(),
        )
        return CHOOSING

    context.user_data["remarks"] = ""

    await query.edit_message_text(
        "Your order:\n\n"
        + order_text(cart)
        + "\n\nPlease type any additional notes, such as less sweet/less ice, or type 'none'"
        + "\n\nTo restart, press /start"
    )

    return REMARKS


async def receive_remarks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    remarks = update.message.text.strip()

    if remarks.lower() == "none":
        remarks = ""

    context.user_data["remarks"] = remarks

    takeaway_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🏠 Dine-in",
                    callback_data="takeaway:no",
                ),
                InlineKeyboardButton(
                    "🥡 Takeaway +$0.20",
                    callback_data="takeaway:yes",
                ),
            ]
        ]
    )

    await update.message.reply_text(
        "Is this order for takeaway? (Applicable to drinks only)",
        reply_markup=takeaway_keyboard,
    )

    return TAKEAWAY


async def receive_takeaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    is_takeaway = query.data == "takeaway:yes"
    context.user_data["takeaway"] = is_takeaway

    await query.edit_message_text(
        "Please enter your collection date and time:"
        "\n Eg 'Tuesday 27/11 11am'"
    )

    return COLLECTION


async def receive_collection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["collection"] = update.message.text.strip()

    if QR_PATH.exists():
        with QR_PATH.open("rb") as qr_image:
            await update.message.reply_photo(
                qr_image,
                caption=(
                    "Thank you! Please make payment using this QR code, then send a "
                    "screenshot of your payment proof here. \n\nPlease remember to add 20c for takeaway drinks"
                ),
            )
    else:
        await update.message.reply_text(
            "Please complete payment, then send a screenshot "
            "of your payment proof here."
        )

    return PAYMENT


async def receive_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message.photo:
        await update.message.reply_text(
            "Please send the payment proof as an image screenshot."
        )
        return PAYMENT

    payment_file_id = update.message.photo[-1].file_id
    user = update.effective_user

    if user.username:
        username = f"@{user.username}"
    else:
        username = user.full_name

    cart = context.user_data["cart"]
    remarks = context.user_data.get("remarks", "")
    takeaway = context.user_data.get("takeaway", False)
    collection = context.user_data["collection"]

    connection = get_database()

    cursor = connection.execute(
        """
        INSERT INTO orders (
            telegram_user_id,
            username,
            order_json,
            remarks,
            takeaway,
            collection_time,
            payment_file_id,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user.id,
            username,
            json.dumps(cart),
            remarks,
            int(takeaway),
            collection,
            payment_file_id,
            "received",
            datetime.now(timezone.utc).isoformat(),
        ),
    )

    order_id = cursor.lastrowid

    connection.commit()
    connection.close()

    notification = (
        f"🔔 New preorder\n\n"
        f"Ordered by: {username}\n"
        f"Order:\n{order_text(cart, takeaway)}\n\n"
        f"Takeaway: {'Yes' if takeaway else 'No'}\n"
        f"Remarks: {remarks or 'None'}\n"
        f"Collection: {collection}"
    )

    await context.bot.send_message(
        chat_id=GROUP_ID,
        text=notification,
    )

    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=payment_file_id,
        caption=(
            f"Payment proof for preorder #{order_id} "
            f"from {username}"
        ),
    )

    await update.message.reply_text(
        f"✅ Your order has been received!\n"
        "\nThank you so much for supporting expeds ☺️. Remember to head down during your indicated collection time to retrieve your order."
        "\n\nTo start a new order, press /start",
        reply_markup=main_keyboard(),
    )

    context.user_data.clear()

    return ConversationHandler.END


async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Order cancelled."
        )
    else:
        await update.message.reply_text(
            "Order cancelled.",
            reply_markup=main_keyboard(),
        )

    return ConversationHandler.END


async def admin_reload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        load_menu()
        await update.message.reply_text(
            "✅ Menu configuration loaded successfully."
        )
    except Exception as error:
        await update.message.reply_text(
            f"❌ Menu error: {error}"
        )


def build_app():
    app = Application.builder().token(TOKEN).build()

    order_conversation = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex("^🛒 Order$"),
                begin_order,
            )
        ],
        states={
            CHOOSING: [
                CallbackQueryHandler(
                    category,
                    pattern=r"^cat:",
                ),
                CallbackQueryHandler(
                    add_item,
                    pattern=r"^add:",
                ),
                CallbackQueryHandler(
                    categories,
                    pattern=r"^categories$",
                ),
                CallbackQueryHandler(
                    review,
                    pattern=r"^review$",
                ),
                CallbackQueryHandler(
                    cancel,
                    pattern=r"^cancel$",
                ),
            ],
            REMARKS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_remarks,
                )
            ],
            TAKEAWAY: [
                CallbackQueryHandler(
                    receive_takeaway,
                    pattern=r"^takeaway:",
                )
            ],
            COLLECTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_collection,
                )
            ],
            PAYMENT: [
                MessageHandler(
                    filters.PHOTO,
                    receive_payment,
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_payment,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(
                cancel,
                pattern=r"^cancel$",
            ),
        ],
    )

    app.add_handler(order_conversation)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reload_menu", admin_reload))

    app.add_handler(
        MessageHandler(
            filters.Regex("^📋 Show menu$"),
            show_menu,
        )
    )

    return app


if __name__ == "__main__":
    log.info("Starting preorder bot")

    build_app().run_polling(
        allowed_updates=Update.ALL_TYPES
    )