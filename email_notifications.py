import smtplib
from email.mime.text import MIMEText
from email.header import Header


def send_notification(subject: str, text: str):
    host = 'mail.sevtelecom.ru'
    server_login = 'irudenko'
    server_password = '1qaz2wsx!'

    to_addresses = ['atemnyh@sevtelecom.ru', 'irudenko@sevtelecom.ru']
    from_address = 'irudenko@sevtelecom.ru'

    message = MIMEText(text, 'plain', 'utf-8')
    message['Subject'] = Header(subject, 'utf-8')
    message['From'] = 'ZABBIX@sevtelecom.ru'
    message['To'] = 'irudenko@sevtelecom.ru'

    with smtplib.SMTP(host, 587) as server:
        print(server.help())
        server.login(server_login, server_password)
        server.sendmail('irudenko@sevtelecom.ru', to_addresses, message.as_string())
        server.quit()


send_notification(subject='Кольцо было развернуто',
                  text='Оборудование в кольце:\n'
                       '                      SVSL-01-MotR-SSW1\n'
                       '                      GP15-Tech623in-ASW2\n'
                       '                      SVSL-01-MotR-ASW1\n'
                       '                      SVSL-01-MotR-ASW2\n'
                       '                      SVSL-01-MotR-ASW3\n'
                       '\nНа узле сети SVSL-01-MotR-SSW1 статус порта GigibitEthernet0/0/1 - "admin down" '
                       'в сторону узла GP15-Tech623in-ASW2')

