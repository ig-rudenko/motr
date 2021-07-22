#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import yaml
import sys
import os
import subprocess
from datetime import datetime
from pprint import pprint
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import core.email_notifications as email
from core.intf_view import interface_normal_view
from core.tc import TelnetConnect
from core.tg_bot_notification import tg_bot_send
from core.funcs import successor_finder, sorted_view_ring, get_ring, rotate_ring, waiting_for_reload_ring, \
    is_all_available, reset_successor, delete_ring_from_deploying_list
from core.device_control import ping_devices, search_admin_down, get_interfaces, compare_ping_status
from core.config import get_config

root_dir = sys.path[0]  # Полный путь к корневой папки


def create_rotate_mark(current_ring_name: str, admin_down: dict, rotate_status: str, rotate_time: datetime):
    # Делаем метку о развороте в файле rotated_rings.yaml
    with open(f'{root_dir}/rotated_rings.yaml', 'r') as rotated_rings_file:
        rotated_rings = yaml.safe_load(rotated_rings_file)
    if not rotated_rings:
        rotated_rings = {}
    del admin_down['session']
    pprint(admin_down)
    rotate_time = str(rotate_time)
    rotated_rings[current_ring_name] = {
        'status': rotate_status,
        'admin_down': admin_down,
        'rotate_time': rotate_time
    }
    with open(f'{root_dir}/rotated_rings.yaml', 'w') as rotated_rings_file:
        yaml.dump(rotated_rings, rotated_rings_file, default_flow_style=False)  # Переписываем файл


def rotate(current_ring: dict, current_ring_list: list, current_ring_name: str, ping_status: list, rotate_type: str,
           this_is_the_second_loop: bool = False):

    def logprint(*text, **kwargs):
        log_text: str = str(datetime.now().strftime('%d.%b.%Y %H:%M:%S')) + ' | ' + ' '.join([str(t) for t in text])
        print(log_text, kwargs if kwargs else '')
        # with open(f'{root_dir}/logs/{date.today()}/{current_ring_name.replace("/", "_")}', 'a') as logfile:
        #     logfile.write(f'{log_text}\n')

    def notification_about_ring_rotate_status(status_string: str, admin_down_device: dict, enable_email=True,
                                              enable_telegram_bot=True):
        subject, massage = None, None
        if 'Error' in status_string:
            subject = f'Прерван разворот кольца {current_ring_name}'
            massage = status_string
        if 'Done' in status_string:
            status_after_rotate = sorted_view_ring(
                ring_list=current_ring_list,
                devices_ping=ping_status,
                host=admin_down_device['name'],
                next_host=admin_down_device['to'],
                interface=admin_down_device['interface'],
                with_status=False
            )
            subject = f'Развернуто {current_ring_name} "{rotate_type}"'
            massage = f'Состояние кольца после разворота: \n{status_after_rotate}'
        # Отправка E-Mail
        if enable_email and subject and massage:
            email.send_text(subject=subject, text=massage)
            logprint('Отправлено письмо')
        # Отправка Telegram
        if enable_telegram_bot and subject and massage:
            tg_bot_send(f'{subject}\n\n{massage}')
            logprint('Отправлено сообщение в Телеграм')

    with open(f'{root_dir}/rotated_rings.yaml') as rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
        if not rotated_rings:
            return 0
    if rotated_rings[current_ring_name] != f'Deploying:{os.getpid()}':
        return 0

    if not this_is_the_second_loop:
        logprint('\n'
                 '--------------------------------------------------------------------------------------------------\n'
                 '==================================================================================================\n'
                 '--------------------------------------------------------------------------------------------------\n'
                 )

    # -------INTERFACES COLLECT---------------
    interfaces = {}  # Список устройств и их интерфейсов

    with ThreadPoolExecutor() as admin_down_executor:  # Создаем обработчик для потоков
        for device_name, device_available in ping_status:
            if device_available:
                # Процесс сбора интерфейсов доступного оборудования в многопоточном режиме
                admin_down_executor.submit(
                    get_interfaces,                         # функция для сбора интерфейсов
                    current_ring, device_name, interfaces   # переменные
                )

    # pprint(interfaces)
    logprint('-------INTERFACES COLLECTED------------', len(interfaces))

    # ----------SEARCH ADMIN DOWN------------

    devices_with_admin_down = []
    logprint('START----------SEARCH ADMIN DOWN------------')
    logprint('Проходимся по собранным интерфейсам')
    for dev in interfaces:  # Проходимся по собранным интерфейсам
        logprint(dev)
        result = search_admin_down(         # Ищем admin down порт
            ring_list=current_ring_list,
            checking_device_name=dev,
            interfaces=interfaces[dev]
        )
        if result:  # Если нашли admin down порт, то добавляем его в итоговый список
            devices_with_admin_down.append(result)
    pprint(devices_with_admin_down)
    # Может быть ситуация, когда в кольце более одного устройства с admin down портами, тогда необходимо выбрать
    #   какой и них необходимо оставить, а другие открыть (на кольце должен быть только 1 порт с admin down)
    admin_down = {
        'name': None,
        'ip': None,
        'to': None,
        'interface': None,
        'session': None
    }
    # Admin down, который останется
    # Наивысший приоритет имеет узел, который стоит в самом начале (ведущий), если на данном узле нет admin down,
    #   то выбираем первый из найденных admin down портов
    admin_down_: dict = [dev for dev in devices_with_admin_down if dev["device"] == current_ring_list[0]] or \
        devices_with_admin_down[0]
    admin_down_ = admin_down_[0] if isinstance(admin_down_, list) else admin_down_
    admin_down['name'] = admin_down_['device']
    admin_down['to'] = admin_down_['next_device'][0]
    admin_down['interface'] = admin_down_['interface'][0]
    admin_down['ip'] = current_ring[admin_down['name']]['ip']
    pprint(admin_down)

    # ------------

    # Если имеется более одного устройства с admin down, то необходимо открыть все, кроме ранее выбранного
    if len(devices_with_admin_down) > 0:
        logprint(f'Найдено {len(devices_with_admin_down)} устройств со статусом порта admin down в данном кольце '
              f'({current_ring_name}):', ', '.join([dev['device'] for dev in devices_with_admin_down]))
        # Оставляем один порт со статусом admin down, а остальные открываем
        for dev_with_admin_down in devices_with_admin_down:
            if dev_with_admin_down['device'] != admin_down["name"]:  # Не трогаем на ранее выбранном узле
                logprint(f'Открываем порт на {dev_with_admin_down["device"]}')
                t = TelnetConnect(
                    ip=current_ring[dev_with_admin_down['device']]['ip'],
                    device_name=dev_with_admin_down["device"]
                )
                t.set_authentication()
                t.connect()  # Подключаемся
                t.set_port_status(
                    port=interface_normal_view(dev_with_admin_down["interface"][0]),
                    status='enable'
                )
                t.save_running_configuration()
                t.close()

    logprint(f"Найден узел сети {admin_down['name']} со статусом порта {admin_down['interface']}: "
          f"admin down\nДанный порт ведет к {admin_down['to']}")

    logprint(f'Rotate Type: {rotate_type.upper()}')

    # Если при восстановлении кольца admin down уже имеется на ведущем узле, то разворачивать не надо
    if rotate_type == 'reset' and admin_down['name'] == current_ring_list[0]:
        logprint('При восстановлении кольца admin down уже имеется на ведущем узле - разворачивать не надо!')
        delete_ring_from_deploying_list(current_ring_name)
        logprint('Метка разворота удалена')
        return 0

    # --------SUCCESSOR------------
    logprint('START--------SUCCESSOR------------')
    successor = {}
    if 'rotate' in rotate_type:
        successor = successor_finder(
            current_ring=current_ring,
            current_ring_list=current_ring_list,
            admin_down=admin_down,
            ping_status=ping_status,
            interfaces=interfaces
        )
    elif 'reset' in rotate_type:
        successor = reset_successor(
            ring=current_ring,
            ring_list=current_ring_list,
            admin_down=admin_down,
            interfaces=interfaces
        )
    pprint(successor)
    if successor['name'] == admin_down['name'] and successor['interface'] == admin_down['interface']:
        return 0
    if not successor:
        return 0

    if not this_is_the_second_loop:
        # Если это первая попытка развернуть кольцо, то отправляем сообщение о предстоящем развороте
        status_before = sorted_view_ring(
            ring_list=current_ring_list,
            devices_ping=ping_status,
            host=admin_down["name"],
            next_host=admin_down["to"],
            interface=admin_down["interface"]
        )   # Красиво оформляем содержание

        text = f'Состояние кольца до разворота: \n{status_before}' \
               f'\nБудут выполнены следующие действия:' \
               f'\nЗакрываем порт {successor["interface"]} на {successor["name"]}' \
               f'\nПоднимаем порт {admin_down["interface"]} на {admin_down["name"]}'

        # Отправка E-Mail
        email.send_text(subject=f'Начинаю разворот кольца {current_ring_name}', text=text)
        # Отправка Telegram
        tg_bot_send(f'Начинаю разворот кольца {current_ring_name}\n\n{text}')

    # --------Разворот
    first_rotate = rotate_ring(
        successor=successor,        # Будет закрыт порт
        admin_down=admin_down       # Будет открыт порт
    )
    logprint('Статус разворота:', first_rotate)
    first_rotate_time = datetime.now()
    notification_about_ring_rotate_status(status_string=first_rotate, admin_down_device=successor)
    if 'reset' in rotate_type:
        # Если тип разворота кольца - СБРОС
        return 0
    # Ecли произошла ошибка во время разворота, то заканчиваем выполнение программы
    if 'Error' in first_rotate:
        return 0
    logprint('Ожидаем, пока поднимутся коммутаторы')
    # Далее необходимо выждать время, чтобы коммутаторы поднялись
    new_ping_status = waiting_for_reload_ring(current_ring, ping_status)
    pprint(new_ping_status)
    if compare_ping_status(ping_status, new_ping_status, ring_list=current_ring_list):
        logprint('После разворота ситуация не изменилась')
        # После разворота ситуация не изменилась
        if not successor['name'] == current_ring_list[0]:  # Если порт не был закрыт на ведущем узле (агрегации)
            if admin_down['name'] == current_ring_list[0]:    # Но Был до этого
                # Разворачиваем кольцо обратно
                logprint('Разворачиваем кольцо обратно')
                reverse_rotate = rotate_ring(
                    successor=admin_down,   # Будет закрыт порт
                    admin_down=successor    # Будет открыт порт
                )
                # Отправляем оповещения
                notification_about_ring_rotate_status(status_string=reverse_rotate, admin_down_device=admin_down)
                return 0
            else:
                # Делаем метку о развороте в файле rotated_rings.yaml
                create_rotate_mark(current_ring_name=current_ring_name,
                                   admin_down=successor,
                                   rotate_status='rotated',
                                   rotate_time=first_rotate_time)
                logprint('Метка разворота: rotated')
                return 1
        else:
            # Если порт в данный момент закрыт на ведущем узле (агрегации), то удаляем метку разворота
            return 0
    else:

        if is_all_available(new_ping_status):

            if this_is_the_second_loop:
                # Если на втором проходе у нас при развороте кольца, снова все узлы доступны, то
                # это обрыв кабеля, в таком случае оставляем кольцо в развернутом виде
                logprint(f'Проблема находится между {successor["name"]} и {successor["to"]}')
                subject = f'{current_ring_name} Возможен обрыв кабеля между {successor["name"]} и {successor["to"]}'
                status_after_rotate = sorted_view_ring(
                    ring_list=current_ring_list,
                    devices_ping=new_ping_status,
                    host=successor['name'],
                    next_host=successor['to'],
                    interface=successor['interface']
                )
                text = f'Кольцо было развернуто:\n{status_after_rotate}'

                email.send_text(subject, text)
                tg_bot_send(f'{subject}\n{text}')

                # Делаем метку о развороте в файле rotated_rings.yaml
                create_rotate_mark(current_ring_name=current_ring_name,
                                   admin_down=successor,
                                   rotate_status='break',
                                   rotate_time=first_rotate_time)
                logprint('Метка разворота: break')
                return 1

            # Если после разворота все узлы сети доступны, то это может быть обрыв кабеля, либо
            #   временное отключение электроэнергии. Разворачиваем кольцо в исходное состояние,
            #   чтобы определить какой именно у нас случай
            logprint('После разворота все узлы сети доступны, то это может быть обрыв кабеля, либо '
                  'временное отключение электроэнергии. Разворачиваем кольцо в исходное состояние, '
                  'чтобы определить какой именно у нас случай')

            # --------Разворот
            first_rotate = rotate_ring(
                successor=admin_down,  # Будет закрыт порт
                admin_down=successor  # Будет открыт порт
            )
            first_rotate_time = datetime.now()
            notification_about_ring_rotate_status(status_string=first_rotate, admin_down_device=admin_down)
            # Ecли произошла ошибка во время разворота, то заканчиваем выполнение программы
            if 'Error' in first_rotate:
                return 0
            # Далее необходимо выждать время, чтобы коммутаторы поднялись
            logprint('Ожидаем, пока поднимутся коммутаторы')
            new_ping_status = waiting_for_reload_ring(current_ring, ping_status)
            pprint(new_ping_status)
            if is_all_available(new_ping_status):
                if admin_down['name'] != current_ring_list[0]:  # admin down НЕ на ведущем узле
                    successor = reset_successor(
                        ring=current_ring,
                        ring_list=current_ring_list,
                        admin_down=admin_down,
                        interfaces=interfaces
                    )
                    reset_rotate = rotate_ring(
                        successor=successor,  # Будет закрыт порт
                        admin_down=admin_down  # Будет открыт порт
                    )
                    notification_about_ring_rotate_status(status_string=reset_rotate, admin_down_device=successor)
                    # Ecли произошла ошибка во время разворота, то заканчиваем выполнение программы
                    return 0
            else:
                return rotate(
                    current_ring=current_ring,
                    current_ring_list=current_ring_list,
                    current_ring_name=current_ring_name,
                    ping_status=new_ping_status,
                    rotate_type=rotate_type,
                    this_is_the_second_loop=True
                )
        else:
            # Делаем метку о развороте в файле rotated_rings.yaml
            create_rotate_mark(current_ring_name=current_ring_name,
                               admin_down=successor,
                               rotate_status='rotated',
                               rotate_time=first_rotate_time)
            logprint('Метка разворота: rotated')
            return 1


def start(device_name: str, start_type: str, silence_mode: str):
    print('START')
    ring_data: tuple = get_ring(
        device_name=device_name,
        rings_files=rings_files
    )
    if not ring_data:
        return 0

    ring_dict, ring_list, ring_name = ring_data
    with open(f'{root_dir}/rings/rings_status.yaml') as rings_status_file:
        rings_status = yaml.safe_load(rings_status_file)
    if not rings_status.get(ring_name) or rings_status.get(ring_name) == 'no':
        print("Для данного кольца отключен разворот!")
        return 0

    # Создаем файл логов
    if not os.path.exists(f'{root_dir}/logs/{date.today()}'):
        os.makedirs(f'{root_dir}/logs/{date.today()}')
    if not os.path.exists(f'{root_dir}/logs/{date.today()}/{ring_name.replace("/", "_")}'):
        with open(f'{root_dir}/logs/{date.today()}/{ring_name.replace("/", "_")}', 'w+') as w_:
            w_.write('\n')

    if silence_mode == 'enable':
        print('SILENCE')
        subprocess.Popen(
            [f'motr -D \'{args.device_name}\' -M {args.mode} >> {root_dir}/logs/{date.today()}/{ring_name.replace("/", "_")} 2>&1 &'],
            close_fds=True,
            shell=True
        )
        print(f'motr -D \'{args.device_name}\' -M {args.mode} >> {root_dir}/logs/{date.today()}/{ring_name.replace("/", "_")} 2>&1')
        return 0

    # Проверяем файл rotated_rings
    with open(f'{root_dir}/rotated_rings.yaml') as rotated_rings_file:
        rotated_rings = yaml.safe_load(rotated_rings_file)
    if rotated_rings:
        for ring_ in rotated_rings:
            if ring_name == ring_:
                if start_type == 'rotate' or (start_type == 'reset' and 'Deploying' in rotated_rings[ring_]):
                    print('Данное кольцо уже имеется в списке, как развернутое ранее!')
                    return 0
                elif start_type == 'force-rotate' or \
                        (start_type == 'reset' and 'Deploying' not in rotated_rings[ring_]) or \
                        start_type == 'force-reset':
                    # Если принудительный разворот или сброс
                    pass
                else:
                    # Неопределенный параметр - выход
                    return 0

    # Делаем отметку, что данное кольцо уже участвует в развороте
    with open(f'{root_dir}/rotated_rings.yaml') as rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
        print('\n')
        pprint(rotated_rings)
        print('\n')
        if not rotated_rings:
            rotated_rings = {}
        rotated_rings[ring_name] = f'Deploying:{os.getpid()}'
    with open(f'{root_dir}/rotated_rings.yaml', 'w') as rings_yaml:  # Чтение файла
        yaml.dump(rotated_rings, rings_yaml, default_flow_style=False)  # Переписываем файл

    devices_ping_status: list = ping_devices(ring=ring_dict)

    for _, available in devices_ping_status:
        if not available:
            if start_type == 'reset':
                # Если имеется недоступное устройство, то автоматический сброс кольца запрещен
                # Но, если принудительный - разрешен
                return 0
            break
    else:
        if 'reset' not in start_type:
            # Если это не сброс кольца, то разворот не требуется
            print("Все устройства в кольце доступны, разворот не требуется!")
            return 0

    for _, available in devices_ping_status:
        if available:
            break
    else:
        print("Все устройства в кольце недоступны, разворот невозможен!")
        return 0

    status = rotate(
        current_ring=ring_dict,
        current_ring_list=ring_list,
        current_ring_name=ring_name,
        ping_status=devices_ping_status,
        rotate_type=start_type
    )
    if not status:
        delete_ring_from_deploying_list(ring_name)
        print('Метка разворота удалена')


def get_ring_status(device_name: str):
    ring_data: tuple = get_ring(
        device_name=device_name,
        rings_files=rings_files
    )
    if not ring_data:
        return 0
    ring_dict, ring_list, ring_name = ring_data
    ring_is_enable = True
    with open(f'{root_dir}/rings/rings_status.yaml') as rings_status_file:
        rings_status = yaml.safe_load(rings_status_file)
    if not rings_status.get(ring_name) or rings_status.get(ring_name) == 'no':
        ring_is_enable = False
    devices_ping_status: list = ping_devices(ring=ring_dict)

    with open(f'{root_dir}/rotated_rings.yaml', 'r') as rotated_rings_file:
        rotated_rings = yaml.safe_load(rotated_rings_file)
    rotated_status = {}
    ring_status = ''
    if rotated_rings:
        for ring_ in rotated_rings:
            if ring_name == ring_:
                rotated_status = rotated_rings[ring_]
    if rotated_status == 'Deploying':
        ring_status = '    Запущен разворот в данный момент'
    else:
        if isinstance(rotated_status, dict) and rotated_status.get('status') == 'rotated':
            ring_status = f'    Кольцо было развернуто! ({rotated_status["rotate_time"]})'
        if isinstance(rotated_status, dict) and rotated_status.get('status') == 'break':
            ring_status = f'    Был найден обрыв! ({rotated_status["rotate_time"]})\n' \
                          f'    Узел {rotated_status["admin_down"]["name"]} порт {rotated_status["admin_down"]["interface"]}' \
                          f' в сторону {rotated_status["admin_down"]["to"]}'

    # -------INTERFACES COLLECT---------------
    interfaces = {}  # Список устройств и их интервейсов
    with ThreadPoolExecutor() as admin_down_executor:  # Создаем обработчик для потоков
        for device_name, device_available in devices_ping_status:
            if device_available:
                # Процесс сбора интерфейсов доступного оборудования в многопоточном режиме
                admin_down_executor.submit(
                    get_interfaces,  # функция для сбора интерфейсов
                    ring_dict, device_name, interfaces  # переменные
                )

    # ----------SEARCH ADMIN DOWN------------
    devices_with_admin_down = []
    for dev in interfaces:  # Проходимся по собранным интерфейсам
        result = search_admin_down(         # Ищем admin down порт
            ring_list=ring_list,
            checking_device_name=dev,
            interfaces=interfaces[dev]
        )
        if result:  # Если нашли admin down порт, то добавляем его в итоговый список
            devices_with_admin_down.append(result)
    print(f'''
    Кольцо: > {ring_name} <
    Активировано: {'Да ✅' if ring_is_enable else 'Нет ❌'}
''')
    if len(devices_with_admin_down) > 1:
        print(f"Внимание! Найдено {len(devices_with_admin_down)} закрытых порта в данном кольце. Должен быть только 1\n")

    for dev in ring_list:
        ad_interface = [ad["interface"][0] for ad in devices_with_admin_down if ad["device"] == dev]
        next_device = [ad["next_device"][0] for ad in devices_with_admin_down if ad["device"] == dev]
        symbol = ''
        if next_device:
            symbol = "△" if next_device[0] == ring_list[ring_list.index(dev) - 1] else "▽"
        print_line = f'    {"✅" if ["✅" for d in devices_ping_status if d[1] and d[0] == dev] else "❌"} {dev}'
        if symbol == "▽":
            print_line = f'{print_line}\n        { ad_interface[0] if ad_interface else ""} {symbol if symbol else ""}'
        elif symbol == "△":
            print_line = f'        { ad_interface[0] if ad_interface else ""} {symbol if symbol else ""}\n{print_line}'
        print(print_line)
    print('\n', ring_status)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Manager of the Rings')

    parser.add_argument("-D", dest='device_name', help='device name')
    parser.add_argument("-M", dest='mode', help='check, rotate, force-rotate, reset, disable, enable')
    parser.add_argument("--status", dest='ring_status', help='Ring status (disable/enable)')
    parser.add_argument("--silence", dest='silence_mode', help='Silence mode (enable)')

    args = parser.parse_args()

    rings_files = get_config('rings_directory')
    email_notification = get_config('email_notification')
    if args.ring_status:
        ring_data: tuple = get_ring(
            device_name=args.device_name,
            rings_files=rings_files
        )
        if ring_data:
            ring_dict, ring_list, ring_name = ring_data
            with open(f'{root_dir}/rings/rings_status.yaml') as rings_status_file:
                rings_status = yaml.safe_load(rings_status_file)
            rings_status[ring_name] = 'yes' if args.ring_status == 'enable' else 'no'
            with open(f'{root_dir}/rings/rings_status.yaml', 'w') as rings_status_file:
                yaml.dump(rings_status, rings_status_file)
            # status = set_ring_status(
            #     args.device_name,
            #     rings_files,
            #     enable_ring=True if args.ring_status == 'enable' else False
            # )
            print(f'    Кольцо: > {ring_name} <')
            print(f'{"    Статус: Включено" if args.ring_status == "enable" else "    Статус: Отключено"}\n')
            for d in ring_list:
                if d != 'enable':
                    print(f'    {d}')
        else:
            print('    Данное оборудование не найдено в списке колец')
    if args.mode and ('rotate' in args.mode or 'reset' in args.mode):
        start(args.device_name, args.mode, args.silence_mode)
    if args.mode == 'check':
        get_ring_status(args.device_name)
