#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import motr
import yaml
import sys
import os
from datetime import datetime
from main import email_notifications as email
from re import findall
from main.logs import lrprint
from main.config import get_config
from main.device_control import set_port_status
from main.device_control import ping_devices, ping_from_device
from main.validation import validation
from main.tg_bot_notification import tg_bot_send

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])
successor_name = ''

if __name__ == '__main__':

    rings_files = get_config('rings_directory')
    email_notification = get_config('email_notification')

    if (sys.argv[1] == '-D' or sys.argv[1] == '--device') and validation(rings_files):
        if len(sys.argv) == 1:
            lrprint("Не указано имя узла сети!")
            sys.exit()
        if len(sys.argv) > 2:
            dev = sys.argv[2]
            get_ring_ = motr.get_ring(dev, rings_files)
            if not get_ring_:
                sys.exit()
            current_ring, current_ring_list, current_ring_name = get_ring_

            # Заголовок
            lrprint('\n')
            lrprint('-' * 20 + 'NEW SESSION' + '-' * 20)
            lrprint(' ' * 12 + str(datetime.now()))
            lrprint(' ' * ((51 - len(dev)) // 2) + dev + ' ' * ((51 - len(dev)) // 2))
            lrprint('-' * 51)

            with open(f'{root_dir}/rotated_rings.yaml') as rings_yaml:  # Чтение файла
                rotated_rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                for ring in rotated_rings:
                    if current_ring_name == ring and rotated_rings[ring] == 'Deploying':
                        lrprint("Кольцо в данный момент разворачивается!")
                        sys.exit()
                    elif current_ring_name == ring and rotated_rings[ring]['priority'] == 1:           # Найдено
                        lrprint("GOT RING: "+ring)
                        break
                else:
                    lrprint('Кольцо не находится в списке колец требуемых к развороту "по умолчанию"')
                    sys.exit()      # Выход

            devices_ping = ping_devices(current_ring)

            for device_name, device_status in devices_ping:
                if not device_status:
                    lrprint("Не все узлы сети в кольце восстановлены, дальнейший разворот прерван!")
                    break
            else:   # Когда все узлы сети в кольце доступны, то...
                lrprint("ALL DEVICES AVAILABLE!\nНачинаем разворот")

                status_before = ''
                for device in current_ring_list:
                    for dev_name, status in devices_ping:
                        if device == dev_name and not bool(findall('SSW', device)):
                            if status:
                                status_before += ' ' * 10 + f'доступно   {device}\n'
                            else:
                                status_before += ' ' * 10 + f'недоступно {device}\n'

                text = f'Состояние кольца до разворота: \n {status_before}'\
                       f'\nВсе устройства доступны, поэтому возвращаем кольцо в прежнее состояние'\
                       f'\nБудут выполнены следующие действия:'\
                       f'\nЗакрываем порт {rotated_rings[current_ring_name]["default_port"]} '\
                       f'на {rotated_rings[current_ring_name]["default_host"]}\n'\
                       f'Поднимаем порт {rotated_rings[current_ring_name]["admin_down_port"]} '\
                       f'на {rotated_rings[current_ring_name]["admin_down_host"]}'
                email.send_text(subject=f'Восстанавление кольца {current_ring_name}',
                                text=text)
                tg_bot_send(f'Восстанавление кольца {current_ring_name}\n\n{text}')
                # -----------------------------Закрываем порт на default_host------------------------------------------
                try_to_set_port = 2
                while try_to_set_port > 0:
                    lrprint(f'Закрываем порт {rotated_rings[current_ring_name]["default_port"]} '
                          f'на {rotated_rings[current_ring_name]["default_host"]}')
                    operation_port_down = set_port_status(current_ring=current_ring,
                                                          device=rotated_rings[current_ring_name]["default_host"],
                                                          interface=rotated_rings[current_ring_name]["default_port"],
                                                          status="down")
                    # Если поймали исключение, то пробуем еще один раз
                    if 'Exception' in operation_port_down and 'SAVE' not in operation_port_down:
                        try_to_set_port -= 1
                        if try_to_set_port > 1:
                            lrprint('\nПробуем еще один раз закрыть порт\n')
                        continue
                    break

                # ---------------------------Если порт на default_host НЕ закрыли--------------------------------------
                if operation_port_down == 'telnet недоступен':
                    text = f'Не удалось подключиться к {rotated_rings[current_ring_name]["default_host"]} по telnet!'\
                           f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'

                elif operation_port_down == 'неверный логин или пароль':
                    text = f'Не удалось зайти на оборудование {rotated_rings[current_ring_name]["default_host"]} '\
                           f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]}) {operation_port_down}'

                elif operation_port_down == 'cant set down':
                    text = f'На оборудовании {rotated_rings[current_ring_name]["default_host"]} '\
                           f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'\
                           f'не удалось закрыть порт {rotated_rings[current_ring_name]["default_port"]}!'

                elif operation_port_down == 'cant status':
                    text = f'На оборудовании {rotated_rings[current_ring_name]["default_host"]} '\
                           f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'\
                           f'была послана команда закрыть порт {rotated_rings[current_ring_name]["default_port"]},'\
                           f' но не удалось распознать интерфейсы для проверки его состояния(см. логи)\n'\
                           f'Отправлена команда на возврат порта в прежнее состояние (up)'

                elif 'DONT SAVE' in operation_port_down:
                    # открываем порт
                    try_to_set_port = 2
                    while try_to_set_port > 0:
                        lrprint(f'Открываем порт {rotated_rings[current_ring_name]["default_port"]} на '
                              f'{rotated_rings[current_ring_name]["default_host"]}')
                        operation_port_up = set_port_status(current_ring=current_ring,
                                                            device=rotated_rings[current_ring_name]["default_host"],
                                                            interface=rotated_rings[current_ring_name]["default_port"],
                                                            status="up")
                        # Если поймали исключение, то пробуем еще один раз
                        if 'Exception' in operation_port_up and 'SAVE' not in operation_port_up:
                            try_to_set_port -= 1
                            if try_to_set_port > 1:
                                lrprint('\nПробуем еще один раз открыть порт\n')
                            continue
                        break
                    if operation_port_up == 'DONE' or 'DONT SAVE' in operation_port_up:
                        text = f'На оборудовании {rotated_rings[current_ring_name]["default_host"]} '\
                               f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'\
                               f'после закрытия порта {rotated_rings[current_ring_name]["default_port"]} не удалось сохранить '\
                               f'конфигурацию!\nВернул порт в исходное состояние (up)\n'\
                               f'Разворот кольца прерван'

                    else:
                        text = f'На оборудовании {rotated_rings[current_ring_name]["default_host"]} '\
                               f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'\
                               f'после закрытия порта {rotated_rings[current_ring_name]["default_port"]} не удалось сохранить '\
                               f'конфигурацию!\nПопытка поднять порт обратно закончилась неудачей: '\
                               f'{operation_port_up}.\nРазворот кольца прерван'

                elif operation_port_down == 'Exception: cant set port status':
                    text = f'Возникло прерывание в момент закрытия порта {rotated_rings[current_ring_name]["default_port"]} '\
                           f'на оборудовании {rotated_rings[current_ring_name]["default_host"]} '\
                           f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'

                elif 'Exception' in operation_port_down:
                    text = f'Возникло прерывание после подключения к оборудованию '\
                           f'{rotated_rings[current_ring_name]["default_host"]} '\
                           f'({current_ring[rotated_rings[current_ring_name]["default_host"]]["ip"]})'

                # ------------------------------------Если порт на default_host закрыли----------------------------------
                elif operation_port_down == 'DONE':

                    # ---------------------Поднимаем порт на admin_down_device--------------------------------------
                    lrprint(f'Поднимаем порт {rotated_rings[current_ring_name]["admin_down_port"]} '
                          f'на {rotated_rings[current_ring_name]["admin_down_host"]}')
                    operation_port_up = set_port_status(current_ring=current_ring,
                                                        device=rotated_rings[current_ring_name]["admin_down_host"],
                                                        interface=rotated_rings[current_ring_name]["admin_down_port"],
                                                        status="up")

                    # Если проблема возникла до стадии сохранения
                    if 'SAVE' not in operation_port_up and 'DONE' not in operation_port_up:
                        # Восстанавливаем порт на преемнике в исходное состояние (up)
                        lrprint(f'\nВосстанавливаем порт {rotated_rings[current_ring_name]["default_port"]} на '
                                f'{rotated_rings[current_ring_name]["default_host"]} '
                                f'в исходное состояние (up)\n')
                        operation_port_reset = set_port_status(current_ring=current_ring,
                                                               device=rotated_rings[current_ring_name]["default_host"],
                                                               interface=rotated_rings[current_ring_name]["default_port"],
                                                               status="up")
                        if operation_port_reset == 'DONE':
                            text = f'Были приняты попытки развернуть кольцо {current_ring_name}\n'\
                                   f'В процессе выполнения был установлен статус порта '\
                                   f'{rotated_rings[current_ring_name]["default_port"]} у '\
                                   f'{rotated_rings[current_ring_name]["default_host"]} "admin down", '\
                                   f'а затем возникла ошибка: {operation_port_up} на узле '\
                                   f'{rotated_rings[current_ring_name]["admin_down_host"]} в попытке поднять порт '\
                                   f'{rotated_rings[current_ring_name]["admin_down_port"]}\n'\
                                   f'Далее порт {rotated_rings[current_ring_name]["default_port"]} '
                            f'на {rotated_rings[current_ring_name]["default_host"]} был возвращен в исходное состояние (up)'
                            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}', text=text)
                            tg_bot_send(f'Прерван разворот кольца {current_ring_name}\n\n{text}')

                        # Если проблема возникла до стадии сохранения
                        elif 'SAVE' not in operation_port_reset:
                            text = f'Были приняты попытки развернуть кольцо {current_ring_name}\n'\
                                   f'В процессе выполнения был установлен статус порта '\
                                   f'{rotated_rings[current_ring_name]["default_port"]} у '\
                                   f'{rotated_rings[current_ring_name]["default_host"]} "admin down", '\
                                   f'а затем возникла ошибка: {operation_port_up} на узле '\
                                   f'{rotated_rings[current_ring_name]["admin_down_host"]} в попытке поднять порт '\
                                   f'{rotated_rings[current_ring_name]["admin_down_port"]}\nДалее возникла ошибка в процессе '\
                                   f'возврата порта {rotated_rings[current_ring_name]["default_port"]} на '\
                                   f'{rotated_rings[current_ring_name]["default_host"]} в '\
                                   f'исходное состояние (up) \nError: {operation_port_reset}'
                            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}', text=text)
                            tg_bot_send(f'Прерван разворот кольца {current_ring_name}\n\n{text}')

                        # Если проблема возникла на стадии сохранения
                        elif 'SAVE' in operation_port_reset:
                            text = f'Были приняты попытки развернуть кольцо {current_ring_name}\n'\
                                   f'В процессе выполнения был установлен статус порта '\
                                   f'{rotated_rings[current_ring_name]["default_port"]} у '\
                                   f'{rotated_rings[current_ring_name]["default_host"]} "admin down", '\
                                   f'а затем возникла ошибка: {operation_port_up} на узле '\
                                   f'{rotated_rings[current_ring_name]["admin_down_host"]} в попытке поднять порт '\
                                   f'{rotated_rings[current_ring_name]["admin_down_port"]}\n'\
                                   f'Далее порт {rotated_rings[current_ring_name]["default_port"]} '\
                                   f'на {rotated_rings[current_ring_name]["default_host"]} был возвращен в исходное состояние (up), '\
                                   f'но на стадии сохранения возникла ошибка: {operation_port_reset}'\
                                   f'\nПроверьте и сохраните конфигурацию!'
                            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}', text=text)
                            tg_bot_send(f'Прерван разворот кольца {current_ring_name}\n\n{text}')

                    # Если проблема возникла во время стадии сохранения
                    elif 'SAVE' in operation_port_up:
                        text = f'Развернуто кольцо\nДействия: \n' \
                               f'1)  На {rotated_rings[current_ring_name]["default_host"]} порт' \
                               f'{rotated_rings[current_ring_name]["default_port"]} - "admin down" '\
                               f'в сторону узла {rotated_rings[current_ring_name]["default_to"]}\n'\
                               f'2)  На {rotated_rings[current_ring_name]["admin_down_host"]} '\
                               f'порт {rotated_rings[current_ring_name]["admin_down_port"]} '\
                               f'- "up" в сторону узла {rotated_rings[current_ring_name]["admin_down_to"]} '\
                               f'но не была сохранена конфигурация!\n'
                        email.send_text(subject=f'{current_ring_name} Автоматический разворот кольца FTTB', text=text)
                        tg_bot_send(f'{current_ring_name} Автоматический разворот кольца FTTB\n\n{text}')

                    # --------------------------------Порт подняли-----------------------------
                    elif operation_port_up == 'DONE':
                        wait_step = 2
                        all_avaliable = 0
                        while wait_step > 0:
                            # Ждем 50 секунд
                            lrprint('Ожидаем 50 сек, не прерывать\n'
                                  '0                       25                       50с')
                            motr.time_sleep(50)
                            # Пингуем заново все устройства в кольце с агрегации
                            new_ping_status = ping_from_device(current_ring_list[0], current_ring)
                            for _, available in new_ping_status:
                                if not available:
                                    break  # Если есть недоступное устройство
                            else:
                                lrprint("Все устройства в кольце после разворота доступны!\n")
                                all_avaliable = 1  # Если после разворота все устройства доступны
                            if all_avaliable or wait_step == 1:
                                break
                            # Если по истечении 50с остались недоступные устройства, то ждем еще 50с
                            wait_step -= 1

                        if all_avaliable:
                            lrprint("Все устройства в кольце после разворота доступны!\nОтправка e-mail")
                            # Отправка e-mail
                            if email_notification == 'enable':
                                sub, text = motr.convert_result_to_str(current_ring_name, current_ring_list, devices_ping,
                                                                       new_ping_status,
                                                                       rotated_rings[current_ring_name]['default_host'],
                                                                       rotated_rings[current_ring_name]['default_port'],
                                                                       rotated_rings[current_ring_name]['default_to'],
                                                                       rotated_rings[current_ring_name]['admin_down_host'],
                                                                       rotated_rings[current_ring_name]['admin_down_port'],
                                                                       rotated_rings[current_ring_name]['admin_down_to'],
                                                                       info='Кольцо было развернуто в прежнее состояние!')
                                email.send_text(subject=sub, text=text)
                                tg_bot_send(f'{sub}\n\n{text}')

                            motr.delete_ring_from_deploying_list(current_ring_name) # Удаляем кольцо из списка требуемых к развороту
                            sys.exit()      # Завершение работы программы

                        # Если в кольце есть недоступные устройства
                        lrprint("После разворота в положение \"по умолчанию\" появились недоступные узлы сети\n"
                              "Выполняем полную проверку заново!")
                        motr.delete_ring_from_deploying_list(current_ring_name)
                        motr.main(new_ping_status, current_ring, current_ring_list, current_ring_name)
                        sys.exit()
                        # Выход

                    motr.delete_ring_from_deploying_list(current_ring_name)
                    sys.exit()

                # Оповещения
                email.send_text(subject=f'Прерван разворот кольца {current_ring_name}', text=text)
                tg_bot_send(f'Прерван разворот кольца {current_ring_name}\n\n{text}')
                motr.delete_ring_from_deploying_list(current_ring_name)
