import requests
import sys
import os
import yaml
import configparser
from main.config import get_config


class MotrAdminBot:

    def __init__(self, token):
        self.token = token
        self.api_url = f'https://api.telegram.org/bot{token}/'

    def get_updates(self, offset=None, timeout=30):
        method = 'getUpdates'
        params = {'timeout': timeout, 'offset': offset}
        resp = requests.get(self.api_url + method, params)
        if resp:
            result_json = resp.json()['result']
        else:
            result_json = resp
        return result_json

    def send_message(self, chat_id: str, text: str):
        params = {'chat_id': chat_id, 'text': text, "parse_mode": "Markdown"}
        response = requests.post(self.api_url + 'sendMessage', data=params)
        return response

    def get_last_update(self) -> dict:
        get_result = self.get_updates()
        print(len(get_result))
        if len(get_result) > 0:
            last_update = get_result[-1]
        else:
            last_update = False

        print(last_update)
        return last_update


root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])
email_notification = 'enable'

if __name__ == '__main__':
    import motr
    new_offset = None
    bot = MotrAdminBot('1286361113:AAESrIDgYNC-CtBXrNwwejbBuc4OOcX2-0M')

    while True:
        bot.get_updates(new_offset)
        last_update = bot.get_last_update()
        if not last_update:
            continue
        update_id = last_update['update_id']
        chat_text = last_update['message']['text']
        chat_id = last_update['message']['chat']['id']
        chat_name = last_update['message']['chat']['first_name']

        text = chat_text.split()
        print(text)
        for i, key in enumerate(text):
            if key == '/D' or key == '/device':
                if len(text) > i + 1:
                    if len(text) > i + 2 and text[i + 2] == 'show-ring':
                        bot.send_message(chat_id, 'enter password')

                        new_offset = update_id + 1
                        bot.get_updates(new_offset)
                        last_update = bot.get_last_update()
                        update_id = last_update['update_id']
                        chat_text = last_update['message']['text']
                        chat_id = last_update['message']['chat']['id']

                        if chat_text == 'motrpass':
                            get_ring_ = motr.get_ring(text[i + 1])
                            if not get_ring_:
                                new_offset = update_id + 1
                                continue
                            *_, current_ring_name = get_ring_
                            output = current_ring_name.replace('_', '\_').replace('*', '\*')
                            bot.send_message(chat_id, output)
                        else:
                            bot.send_message(chat_id, '*Invalid password!*')

            if key == '/stat':
                rings_count = 0
                devices_count = 0
                rings_files = get_config('rings_directory')
                for file in rings_files:
                    with open(file, 'r') as ff:
                        rings = yaml.safe_load(ff)  # Перевод из yaml в словарь
                    rings_count += len(rings)
                    devrc = 0
                    for r in rings:
                        devrc += len(rings[r])
                    devices_count += devrc
                output = f"total rings count: {rings_count}\ntotal devices count: {devices_count}"
                bot.send_message(chat_id, output)

            if key == '/conf':
                output = f'*Файл конфигурации*:\n{root_dir}/config.conf\n'
                config = configparser.ConfigParser()
                config.read(f'{root_dir}/config.conf')
                output += f'email\_notification = {config.get("Settings", "email_notification")}\n'
                output += f'rings\_directory = {config.get("Settings", "rings_directory")}'
                bot.send_message(chat_id, output)

            if key == '/motr':
                bot.send_message(chat_id, '[Manager of the Ring](https://github.com/ig-rudenko/motr)')

        new_offset = update_id + 1
        print(new_offset)
