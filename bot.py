#!/usr/bin/env python

from redis_facade import RedisFacade
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    Venue,
)
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    Filters,
    MessageHandler,
    Updater,
)

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Dict, Set
import google.protobuf.text_format as text_format
import logging
import os
import proto.conversation_pb2 as conversation_proto
import redis

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSING = range(1)

BACK = "Назад"
START_OVER = "Вернуться в начало"
DONE = "Завершить"
PROMPT_REPLY = "Выберите пункт"

START_NODE = "/start"

CONVERSATION_DATA = {}
PHOTO_CACHE = {}

rdf = None

class S(BaseHTTPRequestHandler):
    def _set_response(self, status):
        self.send_response(status)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        status = 200 if self.path == '/healthz' else 403
        self._set_response(status)


def done(update: Update, context: CallbackContext) -> int:
    user_data = context.user_data

    update.message.reply_text(
        "Спасибо! Напишите /start чтобы начать снова.",
        reply_markup=ReplyKeyboardRemove(),
    )

    user_data.clear()
    return ConversationHandler.END


def start_over(update: Update, context: CallbackContext) -> int:
    logging.info("start_over")
    return start(update, context, False)


def start(update: Update, context: CallbackContext, restore_nav_stack: bool = True) -> int:
    logging.info("start")
    user_data = context.user_data
    if restore_nav_stack:
        recollect_nav_stack(update.message.from_user.id, user_data)
    else:
        reset_navigation(user_data)
    return choice(update, context)


def recollect_nav_stack(user_id: int, user_data: Dict) -> None:
    if "nav_stack" in user_data:
        return
    nav_stack = rdf.load_nav_stack(user_id)
    logging.info(f'Load nav: {nav_stack}')
    if nav_stack is None:
        reset_navigation(user_data)
        return
    # Drop the entire stack if the tree has changed.
    for node_name in nav_stack:
        if not node_name in CONVERSATION_DATA["node_by_name"]:
            reset_navigation(user_data)
            return
    user_data["nav_stack"] = nav_stack
    user_data["current_node"] = nav_stack[-1]


def back_choice(update: Update, context: CallbackContext) -> int:
    logging.info("back_choice")
    user_data = context.user_data
    recollect_nav_stack(update.message.from_user.id, user_data)
    user_data["nav_stack"] = user_data["nav_stack"][:-1] \
        if len(user_data["nav_stack"]) > 1 else user_data["nav_stack"]
    logging.info(f'nav_stack: {user_data["nav_stack"]}')
    new_node_name = user_data["nav_stack"][-1]
    user_data["current_node"] = new_node_name
    return choice(update, context)


def reset_navigation(user_data: Dict) -> None:
    user_data["current_node"] = START_NODE
    user_data["nav_stack"] = [ START_NODE ]


def handle_answer(answer, update: Update):
    if len(answer.text) > 0:
        update.message.reply_text(answer.text, parse_mode=ParseMode.HTML)
    elif len(answer.links.text) > 0:
        links = answer.links
        buttons = []
        for url in links.url:
            buttons.append([InlineKeyboardButton(url.label, url=url.url)])
        reply_markup = InlineKeyboardMarkup(buttons)
        update.message.reply_text(
            links.text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    elif len(answer.venue.title) > 0:
        update.message.reply_venue(
            latitude=answer.venue.lat,
            longitude=answer.venue.lon,
            title=answer.venue.title,
            address=answer.venue.address,
            google_place_id=answer.venue.google_place_id)
    elif len(answer.photo) > 0:
        photob = None
        if answer.photo in PHOTO_CACHE:
            photob = PHOTO_CACHE[answer.photo]
        with open("photo/%s" % answer.photo, 'rb') as photo_file:
            photob = photo_file.read()
            PHOTO_CACHE[answer.photo] = photob
        update.message.reply_photo(photob)


def choice(update: Update, context: CallbackContext) -> int:
    logging.info("choice")
    logging.info(f"from_user: {update.message.from_user.id}")
    user_data = context.user_data
    next_node_name = user_data["current_node"]
    if update.message.text in CONVERSATION_DATA["node_by_name"]:
        next_node_name = update.message.text
    if next_node_name in CONVERSATION_DATA["keyboard_by_name"]:
        user_data["current_node"] = next_node_name
        try:
            existing_index = user_data["nav_stack"].index(next_node_name)
            user_data["nav_stack"] = user_data["nav_stack"][:existing_index]
        except ValueError:
            pass
        user_data["nav_stack"].append(next_node_name)
        rdf.save_nav_stack(update.message.from_user.id, user_data["nav_stack"])
        logging.info(f'Saving nav: {user_data["nav_stack"]}')
    current_node_name = user_data["current_node"]

    current_node = CONVERSATION_DATA["node_by_name"][next_node_name]
    current_keyboard_options = [ *CONVERSATION_DATA["keyboard_by_name"][current_node_name] ]
    if len(user_data["nav_stack"]) > 1:
        current_keyboard_options.append([BACK])
    if next_node_name != START_NODE:
        current_keyboard_options.append([START_OVER])
    current_keyboard = ReplyKeyboardMarkup(current_keyboard_options, one_time_keyboard=True)

    for answer in current_node.answer[:-1]:
        handle_answer(answer, update)

    answer = current_node.answer[-1]
    if len(answer.text) == 0:
        handle_answer(answer, update)
        update.message.reply_text(
            PROMPT_REPLY,
            reply_markup=current_keyboard,
        )
    else:
        update.message.reply_text(
            answer.text,
            parse_mode=ParseMode.HTML,
            reply_markup=current_keyboard,
        )

    return CHOOSING


def start_bot():
    global rdf
    api_key = os.getenv('TELEGRAM_BOT_API_KEY')
    updater = Updater(token=api_key, use_context=True)
    dispatcher = updater.dispatcher

    back_filter = Filters.regex('^(' + BACK + ')$')
    back_handler = MessageHandler(back_filter, back_choice)
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(Filters.all & ~back_filter, start),
                      back_handler],
        states={
            CHOOSING: [
                back_handler,
                MessageHandler(
                    Filters.text & ~Filters.regex('^%s|%s$' % (DONE, START_OVER)), choice),
            ],
        },
        fallbacks=[
            MessageHandler(Filters.regex('%s$' % (START_OVER)), start_over),
            # MessageHandler(Filters.regex('%s$' % (DONE)), done),
        ],
    )
    dispatcher.add_handler(conv_handler)

    rdf = RedisFacade()
    if os.getenv('USE_WEBHOOK', '') == 'true':
        port = int(os.environ.get('TELEGRAM_BOT_PORT', 8443))
        webhook_url = f"https://{os.environ['HEROKU_APP_NAME']}.herokuapp.com/{api_key}"
        logger.log(logging.INFO, "Starting webhook at port %s, webhook url: %s", port, webhook_url)
        updater.start_webhook(listen='0.0.0.0',
                              port=int(port),
                              url_path=api_key,
                              webhook_url=webhook_url)
    else:
        updater.start_polling()

    updater.idle()


def visit_node(node: conversation_proto.ConversationNode, consumer, visited: Set = set()):
    visited.add(node.name)
    consumer(node)
    if len(node.link) > 0:
        for subnode in node.link:
            if len(subnode.branch.name) > 0 and not subnode.branch.name in visited:
                visit_node(subnode.branch, consumer, visited)


def create_node_by_name(conversation: conversation_proto.Conversation):
    node_by_name = {}

    def updater(node):
        node_by_name[node.name] = node
    for node in conversation.node:
        visit_node(node, updater)
    return node_by_name


def create_keyboard_options(node_by_name):
    keyboard_by_name = {}
    for name in node_by_name:
        if len(node_by_name[name].link) > 0:
            options = []
            for link in node_by_name[name].link:
                if len(link.name) > 0:
                    options.append([link.name])
                elif len(link.branch.name) > 0:
                    options.append([link.branch.name])
            keyboard_by_name[name] = options
    return keyboard_by_name


def serve_http():
    port = int(os.environ.get('HEALTHCHECK_PORT', 10000))
    server_address = ('', port)
    httpd = HTTPServer(server_address, S)
    logging.info('Starting httpd...\n')
    httpd.serve_forever()


if __name__ == "__main__":
    with open('conversation_tree.textproto', 'r') as f:
        f_buffer = f.read()
        conversation = text_format.Parse(
            f_buffer, conversation_proto.Conversation())
    CONVERSATION_DATA["node_by_name"] = create_node_by_name(conversation)
    CONVERSATION_DATA["keyboard_by_name"] = create_keyboard_options(
        CONVERSATION_DATA["node_by_name"])
    thread = Thread(target=serve_http, name='HTTP Server', daemon=True)
    thread.start()
    start_bot()
