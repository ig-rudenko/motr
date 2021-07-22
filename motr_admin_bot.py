import requests


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
