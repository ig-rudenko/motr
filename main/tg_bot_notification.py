from motr_admin_bot import MotrAdminBot
from main.config import set_default_config, get_config
import os
import sys

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])


def tg_bot_send(text: str):
    if not os.path.exists(f'{root_dir}/config.conf'):
        set_default_config()

    if get_config('tg_bot_notification') == 'enable':
        token = get_config('TG_bot_token')
        chat_id = get_config('TG_bot_chat_id')

        telegram_bot = MotrAdminBot(token)
        telegram_bot.send_message(chat_id, text)
