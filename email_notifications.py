import smtplib
from email.mime.text import MIMEText
from email.header import Header
from re import findall


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
    host = 'mail.sevtelecom.ru'
    server_login = 'irudenko'
    server_password = '1qaz2wsx!'

    to_addresses = ['atemnyh@sevtelecom.ru', 'irudenko@sevtelecom.ru']
    from_address = 'irudenko@sevtelecom.ru'

    status_before = ''
    status_after = ''

    for device in current_ring_list:
        for dev_name, status in old_devices_ping:
            if device == dev_name and not bool(findall('SSW', device)):
                if status:
                    status_before += ' ' * 10 + f'{device}  доступно\n'
                else:
                    status_before += ' ' * 10 + f'{device}  недоступно\n'

    for device in current_ring_list:
        for dev_name, status in new_devices_ping:
            if device == dev_name and not bool(findall('SSW', device)):
                if status:
                    status_after += ' ' * 10 + f'{device}  доступно\n'
                else:
                    status_after += ' ' * 10 + f'{device}  недоступно\n'

    subject = f'{ring_name} Автоматический разворот кольца FTTB'

    text = f'Состояние кольца до разворота: \n {status_before}'\
           f'\nДействия: '\
           f'\n1)  На {admin_down_host} порт {admin_down_port} - "admin down" '\
           f'в сторону узла {admin_down_to}\n'\
           f'2)  На {up_host} порт {up_port} - "up" '\
           f'в сторону узла {up_to}\n'\
           f'\nСостояние кольца после разворота: \n {status_after} \n'\
           f'{info}'

    message = MIMEText(text, 'plain', 'utf-8')
    message['Subject'] = Header(subject, 'utf-8')
    message['From'] = 'ZABBIX@sevtelecom.ru'
    message['To'] = 'irudenko@sevtelecom.ru'

    with smtplib.SMTP(host, 587) as server:
        server.login(server_login, server_password)

        server.sendmail(from_addr='irudenko@sevtelecom.ru',
                        to_addrs=to_addresses[1],
                        msg=message.as_string())
        server.quit()


if __name__ == '__main__':

    ring_name = '12-Kosareva2-SSW2_p21_p22'
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
