#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import motr
import yaml
import sys
import os
from datetime import datetime
import email_notifications as email
from re import findall

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])
successor_name = ''
email_notification = 'enable'
rings_files = []

if __name__ == '__main__':

    if len(sys.argv) == 1:
        print("Не указано имя узла сети!")
        sys.exit()
    motr.get_config()
    if not motr.validation(rings_files):
        sys.exit()

    dev = sys.argv[1]
    get_ring_ = motr.get_ring(dev)
    if not get_ring_:
        sys.exit()
    current_ring, current_ring_list, current_ring_name = get_ring_

    # Заголовок
    print('\n')
    print('-' * 20 + 'NEW SESSION' + '-' * 20)
    print(' ' * 12 + str(datetime.now()))
    print(' ' * ((51 - len(dev)) // 2) + dev + ' ' * ((51 - len(dev)) // 2))
    print('-' * 51)

    with open(f'{root_dir}/rotated_rings.yaml') as rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
        for ring in rotated_rings:
            if current_ring_name == ring and rotated_rings[ring] == 'Deploying':
                print("Кольцо в данный момент разворачивается!")
                sys.exit()
            elif current_ring_name == ring and rotated_rings[ring]['priority'] == 1:           # Найдено
                print("GOT RING: "+ring)
                break
        else:
            print('Кольцо не находится в списке колец требуемых к развороту "по умолчанию"')
            sys.exit()      # Выход

    devices_ping = motr.ping_devices(current_ring)

    for device_name, device_status in devices_ping:
        if not device_status:
            print("Не все узлы сети в кольце восстановлены, дальнейший разворот прерван!")
            break
    else:   # Когда все узлы сети в кольце доступны, то...
        print("ALL DEVICES AVAILABLE!\nНачинаем разворот")

        status_before = ''
        for device in current_ring_list:
            for dev_name, status in devices_ping:
                if device == dev_name and not bool(findall('SSW', device)):
                    if status:
                        status_before += ' ' * 10 + f'доступно   {device}\n'
                    else:
                        status_before += ' ' * 10 + f'недоступно {device}\n'

        email.send_text(subject=f'Восстанавление кольца {current_ring_name}',
                        text=f'Состояние кольца до разворота: \n {status_before}'
                             f'\nВсе устройства доступны, поэтому возвращаем кольцо в прежнее состояние'
                             f'\nБудут выполнены следующие действия:'
                             f'\nЗакрываем порт {rotated_rings[current_ring_name]["default_port"]} '
                             f'на {rotated_rings[current_ring_name]["default_host"]}\n'
                             f'Поднимаем порт {rotated_rings[current_ring_name]["admin_down_port"]} '
                             f'на {rotated_rings[current_ring_name]["admin_down_host"]}')
        # -----------------------------Закрываем порт на default_host------------------------------------------
        try_to_set_port = 2
        while try_to_set_port > 0:
            print(f'Закрываем порт {rotated_rings[current_ring_name]["default_port"]} '
                  f'на {rotated_rings[current_ring_name]["default_host"]}')
            operation_port_down = motr.set_port_status(current_ring=current_ring,
                                                       device=rotated_rings[current_ring_name]["default_host"],
                                                       interface=rotated_rings[current_ring_name]["default_port"],
                                                       status="down")
            # Если поймали исключение, то пробуем еще один раз
            if 'Exception' in operation_port_down and 'SAVE' not in operation_port_down:
                try_to_set_port -= 1
                if try_to_set_port > 1:
                    print('\nПробуем еще один раз закрыть порт\n')
                continue
            break

        # ---------------------------Если порт на default_host НЕ закрыли--------------------------------------
        if operation_port_down == 'telnet недоступен':
            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                            text=f'Не удалось подключиться к {rotated_rings[current_ring_name]["default_host"]} по telnet!'
                                 f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})')

        elif operation_port_down == 'неверный логин или пароль':
            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                            text=f'Не удалось зайти на оборудование {rotated_rings[current_ring_name]["default_host"]} '
                                 f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]}) {operation_port_down}')

        elif operation_port_down == 'cant set down':
            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                            text=f'На оборудовании {rotated_rings[current_ring_name]["default_host"]} '
                                 f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'
                                 f'не удалось закрыть порт {rotated_rings[current_ring_name]["default_port"]}!')

        elif operation_port_down == 'cant status':
            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                            text=f'На оборудовании {rotated_rings[current_ring_name]["default_host"]} '
                                 f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'
                                 f'была послана команда закрыть порт {rotated_rings[current_ring_name]["default_port"]},'
                                 f' но не удалось распознать интерфейсы для проверки его состояния(см. логи)\n'
                                 f'Отправлена команда на возврат порта в прежнее состояние (up)')

        elif 'DONT SAVE' in operation_port_down:
            # открываем порт
            try_to_set_port = 2
            while try_to_set_port > 0:
                print(f'Открываем порт {rotated_rings[current_ring_name]["default_port"]} на '
                      f'{rotated_rings[current_ring_name]["default_host"]}')
                operation_port_up = motr.set_port_status(current_ring=current_ring,
                                                         device=rotated_rings[current_ring_name]["default_host"],
                                                         interface=rotated_rings[current_ring_name]["default_port"],
                                                         status="up")
                # Если поймали исключение, то пробуем еще один раз
                if 'Exception' in operation_port_up and 'SAVE' not in operation_port_up:
                    try_to_set_port -= 1
                    if try_to_set_port > 1:
                        print('\nПробуем еще один раз открыть порт\n')
                    continue
                break
            if operation_port_up == 'DONE' or 'DONT SAVE' in operation_port_up:
                email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                text=f'На оборудовании {rotated_rings[current_ring_name]["default_host"]} '
                                     f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'
                                     f'после закрытия порта {rotated_rings[current_ring_name]["default_port"]} не удалось сохранить '
                                     f'конфигурацию!\nВернул порт в исходное состояние (up)\n'
                                     f'Разворот кольца прерван')
            else:
                email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                text=f'На оборудовании {rotated_rings[current_ring_name]["default_host"]} '
                                     f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'
                                     f'после закрытия порта {rotated_rings[current_ring_name]["default_port"]} не удалось сохранить '
                                     f'конфигурацию!\nПопытка поднять порт обратно закончилась неудачей: '
                                     f'{operation_port_up}.\n'
                                     f'Разворот кольца прерван')
            sys.exit()
            # Выход

        elif operation_port_down == 'Exception: cant set port status':
            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                            text=f'Возникло прерывание в момент закрытия порта {rotated_rings[current_ring_name]["default_port"]} '
                                 f'на оборудовании {rotated_rings[current_ring_name]["default_host"]} '
                                 f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})')

        elif 'Exception' in operation_port_down:
            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                            text=f'Возникло прерывание после подключения к оборудованию '
                                 f'{rotated_rings[current_ring_name]["default_host"]} '
                                 f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})')

        # ------------------------------------Если порт на default_host закрыли----------------------------------
        elif operation_port_down == 'DONE':

            # ---------------------Поднимаем порт на admin_down_device--------------------------------------
            print(f'Поднимаем порт {rotated_rings[current_ring_name]["admin_down_port"]} '
                  f'на {rotated_rings[current_ring_name]["admin_down_host"]}')
            operation_port_up = motr.set_port_status(current_ring=current_ring,
                                                     device=rotated_rings[current_ring_name]["admin_down_host"],
                                                     interface=rotated_rings[current_ring_name]["admin_down_port"],
                                                     status="up")

            # Если проблема возникла до стадии сохранения
            if 'SAVE' not in operation_port_up and 'DONE' not in operation_port_up:
                # Восстанавливаем порт на преемнике в исходное состояние (up)
                print(f'\nВосстанавливаем порт {rotated_rings[current_ring_name]["default_port"]} на '
                      f'{rotated_rings[current_ring_name]["default_host"]} '
                      f'в исходное состояние (up)\n')
                operation_port_reset = motr.set_port_status(current_ring=current_ring,
                                                            device=rotated_rings[current_ring_name]["default_host"],
                                                            interface=rotated_rings[current_ring_name]["default_port"],
                                                            status="up")
                if operation_port_reset == 'DONE':
                    email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                    text=f'Были приняты попытки развернуть кольцо {current_ring_name}\n'
                                         f'В процессе выполнения был установлен статус порта '
                                         f'{rotated_rings[current_ring_name]["default_port"]} у '
                                         f'{rotated_rings[current_ring_name]["default_host"]} "admin down", '
                                         f'а затем возникла ошибка: {operation_port_up} на узле '
                                         f'{rotated_rings[current_ring_name]["admin_down_host"]} в попытке поднять порт '
                                         f'{rotated_rings[current_ring_name]["admin_down_port"]}\n'
                                         f'Далее порт {rotated_rings[current_ring_name]["default_port"]} '
                                         f'на {rotated_rings[current_ring_name]["default_host"]} был возвращен в исходное состояние (up)')
                # Если проблема возникла до стадии сохранения
                elif 'SAVE' not in operation_port_reset:
                    email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                    text=f'Были приняты попытки развернуть кольцо {current_ring_name}\n'
                                         f'В процессе выполнения был установлен статус порта '
                                         f'{rotated_rings[current_ring_name]["default_port"]} у '
                                         f'{rotated_rings[current_ring_name]["default_host"]} "admin down", '
                                         f'а затем возникла ошибка: {operation_port_up} на узле '
                                         f'{rotated_rings[current_ring_name]["admin_down_host"]} в попытке поднять порт '
                                         f'{rotated_rings[current_ring_name]["admin_down_port"]}\nДалее возникла ошибка в процессе '
                                         f'возврата порта {rotated_rings[current_ring_name]["default_port"]} на '
                                         f'{rotated_rings[current_ring_name]["default_host"]} в '
                                         f'исходное состояние (up) \nError: {operation_port_reset}')
                # Если проблема возникла на стадии сохранения
                elif 'SAVE' in operation_port_reset:
                    email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                    text=f'Были приняты попытки развернуть кольцо {current_ring_name}\n'
                                         f'В процессе выполнения был установлен статус порта '
                                         f'{rotated_rings[current_ring_name]["default_port"]} у '
                                         f'{rotated_rings[current_ring_name]["default_host"]} "admin down", '
                                         f'а затем возникла ошибка: {operation_port_up} на узле '
                                         f'{rotated_rings[current_ring_name]["admin_down_host"]} в попытке поднять порт '
                                         f'{rotated_rings[current_ring_name]["admin_down_port"]}\n'
                                         f'Далее порт {rotated_rings[current_ring_name]["default_port"]} '
                                         f'на {rotated_rings[current_ring_name]["default_host"]} был возвращен в исходное состояние (up), '
                                         f'но на стадии сохранения возникла ошибка: {operation_port_reset}'
                                         f'\nПроверьте и сохраните конфигурацию!')

            # Если проблема возникла во время стадии сохранения
            elif 'SAVE' in operation_port_up:
                email.send_text(subject=f'{current_ring_name} Автоматический разворот кольца FTTB',
                                text=f'Развернуто кольцо'
                                     f'\nДействия: '
                                     f'\n1)  На {rotated_rings[current_ring_name]["default_host"]} порт '
                                     f'{rotated_rings[current_ring_name]["default_port"]} - "admin down" '
                                     f'в сторону узла {rotated_rings[current_ring_name]["default_to"]}\n'
                                     f'2)  На {rotated_rings[current_ring_name]["admin_down_host"]} '
                                     f'порт {rotated_rings[current_ring_name]["admin_down_port"]} '
                                     f'- "up" в сторону узла {rotated_rings[current_ring_name]["admin_down_to"]} '
                                     f'но не была сохранена конфигурация!\n')

            # --------------------------------Порт подняли-----------------------------
            elif operation_port_up == 'DONE':
                wait_step = 2
                all_avaliable = 0
                while wait_step > 0:
                    # Ждем 50 секунд
                    print('Ожидаем 50 сек, не прерывать\n'
                          '0                       25                       50с')
                    motr.time_sleep(50)
                    # Пингуем заново все устройства в кольце с агрегации
                    new_ping_status = motr.ping_from_device(current_ring_list[0], current_ring)
                    for _, available in new_ping_status:
                        if not available:
                            break  # Если есть недоступное устройство
                    else:
                        print("Все устройства в кольце после разворота доступны!\n")
                        all_avaliable = 1  # Если после разворота все устройства доступны
                    if all_avaliable or wait_step == 1:
                        break
                    # Если по истечении 50с остались недоступные устройства, то ждем еще 50с
                    wait_step -= 1

                if all_avaliable:
                    print("Все устройства в кольце после разворота доступны!\nОтправка e-mail")
                    # Отправка e-mail
                    if email_notification == 'enable':
                        email.send(current_ring_name, current_ring_list, devices_ping, new_ping_status,
                                   rotated_rings[current_ring_name]['default_host'],
                                   rotated_rings[current_ring_name]['default_port'],
                                   rotated_rings[current_ring_name]['default_to'],
                                   rotated_rings[current_ring_name]['admin_down_host'],
                                   rotated_rings[current_ring_name]['admin_down_port'],
                                   rotated_rings[current_ring_name]['admin_down_to'])

                    motr.delete_ring_from_deploying_list(current_ring_name) # Удаляем кольцо из списка требуемых к развороту
                    sys.exit()      # Завершение работы программы

                # Если в кольце есть недоступные устройства
                print("После разворота в положение \"по умолчанию\" появились недоступные узлы сети\n"
                      "Выполняем полную проверку заново!")
                motr.delete_ring_from_deploying_list(current_ring_name)
                motr.main(new_ping_status, current_ring, current_ring_list, current_ring_name)
                sys.exit()
                # Выход

        motr.delete_ring_from_deploying_list(current_ring_name)