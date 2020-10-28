
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import configparser
import os
import sys
from main.config import set_default_config, get_config

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])


def to_address() -> list:
    if not os.path.exists(f'{root_dir}/config.conf'):
        set_default_config()
    config = configparser.ConfigParser()
    config.read(f'{root_dir}/config.conf')
    to_addr = config.get("Email", 'to_address').split(',')
    to_address_list = [x.strip() for x in to_addr if to_addr and '@' in x]
    if not to_address_list:                     # Если нет адресов, то...
        to_address_list = ['noc@sevtelecom.ru']     # ...отправляем на noc
    return to_address_list


def send_text(subject: str, text: str):
    if not os.path.exists(f'{root_dir}/config.conf'):
        set_default_config()

    if get_config("email_notification") == 'enable':    # Если включены email оповещения

        host = 'mail.sevtelecom.ru'
        server_login = 'irudenko'
        server_password = '1qaz2wsx!'

        to_addresses = to_address()

        message = MIMEText(text, 'plain', 'utf-8')
        message['Subject'] = Header(subject, 'utf-8')
        message['From'] = 'ZABBIX@sevtelecom.ru'
        message['To'] = 'irudenko@sevtelecom.ru'

        with smtplib.SMTP(host, 587) as server:
            server.login(server_login, server_password)

            server.sendmail(from_addr='irudenko@sevtelecom.ru',
                            to_addrs=to_addresses,
                            msg=message.as_string())
            server.quit()


if __name__ == '__main__':

    # ДЛЯ ТЕСТА
    ring_name = 'ТЕСТОВОЕ ПИСЬМО'
    info = '\nВозможен обрыв кабеля между SVSL-01-MotR-SSW1 и GP15-Tech623in-ASW2\n'
    devices_ping = [
        ('SVSL-01-MotR-SSW1', True),
        ('GP15-Tech623in-ASW2', False),
        ('SVSL-01-MotR-ASW3', False),
        ('SVSL-01-MotR-ASW2', False),
        ('SVSL-01-MotR-ASW1', False)
    ]
    new_devices_ping = [
        ('SVSL-01-MotR-SSW1', True),
        ('GP15-Tech623in-ASW2', True),
        ('SVSL-01-MotR-ASW3', True),
        ('SVSL-01-MotR-ASW2', True),
        ('SVSL-01-MotR-ASW1', True)
    ]
    current_ring_list = ['SVSL-01-MotR-SSW1',
                         'GP15-Tech623in-ASW2',
                         'SVSL-01-MotR-ASW1',
                         'SVSL-01-MotR-ASW2',
                         'SVSL-01-MotR-ASW3']
    admin_down_host = 'SVSL-01-MotR-SSW1'
    admin_down_port = 'GigibitEthernet0/0/1'
    admin_down_to = 'GP15-Tech623in-ASW2'
    up_host = 'SVSL-01-MotR-SSW1'
    up_port = 'GigibitEthernet0/0/2'
    up_to = 'SVSL-01-MotR-ASW3'

    # send(ring_name, current_ring_list, devices_ping, new_devices_ping, admin_down_host, admin_down_port, admin_down_to,
    #      up_host, up_port, up_to, info)

    send_text(subject='Тестовое письмо', text='Привет :)')
