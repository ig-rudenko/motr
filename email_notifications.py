import smtplib
from email.mime.text import MIMEText
from email.header import Header
from re import findall
import configparser
import os
import sys

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])


def to_address() -> list:
    if not os.path.exists(f'{root_dir}/config.conf'):
        config = configparser.ConfigParser()
        config.add_section('Settings')
        config.set("Settings", 'email_notification', 'enable')
        config.set("Settings", 'rings_directory', '~rings/*')
        config.set("Email", 'to_address', 'noc@sevtelecom.ru')
        with open('config.conf', 'w') as cf:
            config.write(cf)
    config = configparser.ConfigParser()
    config.read(f'{root_dir}/config.conf')
    to_addr = config.get("Email", 'to_address').split(',')
    to_address_list = [x.strip() for x in to_addr if to_addr and '@' in x]
    if not to_address_list:
        to_address_list = ['noc@sevtelecom.ru']
    return to_address_list


def send_text(subject: str, text: str):
    host = 'mail.sevtelecom.ru'
    server_login = 'irudenko'
    server_password = '1qaz2wsx!'

    to_addresses = ['atemnyh@sevtelecom.ru', 'irudenko@sevtelecom.ru', 'noc@sevtelecom.ru']
    to_addresses = to_address()
    from_address = 'irudenko@sevtelecom.ru'

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


def send(ring_name: str, current_ring_list: list, old_devices_ping: list, new_devices_ping: list,
         admin_down_host: str, admin_down_port: str, admin_down_to: str, up_host: str, up_port: str,
         up_to: str, info: str = ''):
    '''
                        Отправка e-mail \n
    :param ring_name:           Имя кольца
    :param current_ring_list:   Кольцо
    :param old_devices_ping:    Состояние узлов сети в кольце до разворота
    :param new_devices_ping:    Состояние узлов сети в кольце после разворота
    :param admin_down_host:     Узел сети со статусом "admin down"
    :param admin_down_port:     Порт узла сети со статусом "admin down"
    :param admin_down_to:       Узел сети, к которому ведет порт со статусом "admin down"
    :param up_host:             Узел сети, который имел статус "admin down" и был поднят
    :param up_port:             Порт узла сети, который имел статус "admin down" и был поднят
    :param up_to:               Узел сети, к которому ведет порт узла сети, который имел статус "admin down" и был поднят
    :param info:                Дополнительная информация
    :return:
    '''

    stat = ['', '']
    dev_stat = [old_devices_ping, new_devices_ping]
    for position, _ in enumerate(dev_stat):
        for device in current_ring_list:
            for dev_name, status in dev_stat[position]:
                if device == dev_name and not bool(findall('SSW', device)):
                    if status:
                        stat[position] += ' ' * 10 + f'доступно   {device}\n'
                    else:
                        stat[position] += ' ' * 10 + f'недоступно {device}\n'

    subject = f'{ring_name} Автоматический разворот кольца FTTB'

    if stat[0] == stat[1]:
        info += '\nНичего не поменялось, знаю, но так надо :)'

    text = f'Состояние кольца до разворота: \n {stat[0]}'\
           f'\nДействия: '\
           f'\n1)  На {admin_down_host} порт {admin_down_port} - "admin down" '\
           f'в сторону узла {admin_down_to}\n'\
           f'2)  На {up_host} порт {up_port} - "up" '\
           f'в сторону узла {up_to}\n'\
           f'\nСостояние кольца после разворота: \n {stat[1]} \n'\
           f'{info}'

    send_text(subject=subject,
              text=text)


if __name__ == '__main__':

    # ДЛЯ ТЕСТА
    ring_name = 'IGNORE_THIS_12-Kosareva2-SSW2_p21_p22'
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

    send(ring_name, current_ring_list, devices_ping, new_devices_ping, admin_down_host, admin_down_port, admin_down_to,
         up_host, up_port, up_to, info)
