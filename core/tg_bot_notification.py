from motr_admin_bot import MotrAdminBot
from core.config import set_default_config, get_config
import os
import sys


def tg_bot_send(text: str):
    if not os.path.exists(f'{sys.path[0]}/config.conf'):
        set_default_config()

    if get_config('tg_bot_notification') == 'enable':
        token = get_config('TG_bot_token')
        chat_id_raw = get_config('TG_bot_chat_id')
        chat_id_list = chat_id_raw.split(',')
        for chat_id in chat_id_list:
            telegram_bot = MotrAdminBot(token)
            telegram_bot.send_message(chat_id.strip(), text)
