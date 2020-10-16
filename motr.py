#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from concurrent.futures import ThreadPoolExecutor   # Многопоточность
import yaml
from re import findall
import sys
import os
from datetime import datetime
import time
import email_notifications as email     # Отправка Email
from logs import lprint                 # Запись логов
from tabulate import tabulate
from device_control import interfaces, search_admin_down, set_port_status, find_port_by_desc
from device_control import ping_devices, ping_from_device
from config import get_config, set_default_config

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])
global email_notification

def ring_rotate_type(current_ring_list: list, main_dev: str, neighbour_dev: str):
    '''
    На основе двух узлов сети определяется тип "поворота" кольца относительно его структуры описанной в файле
        Positive - так как в списке \n
        Negative - обратный порядок \n
    :param current_ring_list: Кольцо (список)
    :param main_dev:        Узел сети с "admin down"
    :param neighbour_dev:   Узел сети, к которому ведет порт со статусом "admin down" узла сети 'main_dev'
    :return: positive, negative, False
    '''
    main_dev_index = current_ring_list.index(main_dev)
    if current_ring_list[main_dev_index-1] == neighbour_dev:
        return "positive"
    elif current_ring_list[main_dev_index+1] == neighbour_dev:
        return "negative"
    else:
        return False


def get_ring(device_name: str, rings_files: list) -> tuple:
    '''
    Функция для поиска кольца, к которому относится переданный узел сети \n
    :param device_name: Уникальное имя узла сети
    :return: 1 Кольцо (dict),
             2 Узлы сети в кольце (list)
             3 Имя кольца (str)
    '''
    for file in rings_files:
        with open(file, 'r') as rings_yaml:      # Чтение файла
            rings = yaml.safe_load(rings_yaml)      # Перевод из yaml в словарь
            for ring in rings:                      # Перебираем все кольца
                for device in rings[ring]:              # Перебираем оборудование в кольце%
                    if device == device_name:               # Если нашли переданный узел сети, то...
                        current_ring = rings[ring]              # ...рассматриваем данное кольцо
                        current_ring_list = []
                        current_ring_name = ring
                        for i in current_ring:
                            current_ring_list.append(i)
                        return current_ring, current_ring_list, str(current_ring_name)
    return ()


def delete_ring_from_deploying_list(ring_name: str):
    with open(f'{root_dir}/rotated_rings.yaml', 'r') as rotated_rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rotated_rings_yaml)  # Перевод из yaml в словарь
        del rotated_rings[ring_name]
    with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
        yaml.dump(rotated_rings, save_ring, default_flow_style=False)  # Переписываем файл


def main(devices_ping: list, current_ring: dict, current_ring_list: list, current_ring_name: str,
         this_is_the_second_loop: bool = False) -> None:

    successor_name = ''

    for device_name, device_status in devices_ping:     # Листаем узлы сети и их доступность по "ping"

        lprint('-'*51+'\n'+'-'*51)

        lprint(f"device_name: {device_name} | device_status: {device_status}")
        if device_status:                                   # Если нашли доступное устройство, то...
            admin_down = search_admin_down(current_ring, current_ring_list, device_name)    # ...ищем admin down
            if admin_down:                                  # 0 - host name, [1] - side host name, [2] - interface

                # Делаем отметку, что данное кольцо уже участвует в развороте
                with open(f'{root_dir}/rotated_rings.yaml', 'r') as rings_yaml:  # Чтение файла
                    rotated_rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                    rotated_rings[current_ring_name] = 'Deploying'
                with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
                    yaml.dump(rotated_rings, save_ring, default_flow_style=False)  # Переписываем файл

                lprint(f"Найден узел сети {admin_down['device']} со статусом порта {admin_down['interface'][0]}: "
                      f"admin down\nДанный порт ведет к {admin_down['next_device'][0]}")
                rotate = ring_rotate_type(current_ring_list, admin_down['device'], admin_down['next_device'][0])
                lprint(f'Разворот кольца: {rotate}')
                if rotate == 'positive':
                    index_factor = -1
                elif rotate == 'negative':
                    index_factor = 1
                else:
                    index_factor = 0

                # Создаем список состоящий из двух списков (элементы текущего кольца),
                #   чтобы не выходить за пределы индексации
                double_current_ring_list = current_ring_list + current_ring_list
                # Начальный индекс равен индексу соседнего узла по отношению к узлу сети, где
                #   установлен принудительный обрыв кольца (admin down) в обратную сторону от разворота кольца
                curr_index = current_ring_list.index(admin_down['device'])+index_factor
                iteration = 1
                if index_factor:                    # Если кольцо имеет поворот то...
                    while index_factor:                 # До тех пор, пока не найдем "преемника":
                        for line in devices_ping:           # Листаем список
                            if line[0] == double_current_ring_list[curr_index]:
                                if not line[1]:                     # Если оборудование недоступно, то...
                                    pass                                # ...пропуск
                                else:                               # Если оборудование доступно, то...
                                    successor_index = curr_index        # ...определяем индекс "преемника"
                                    successor_name = double_current_ring_list[successor_index]
                                    index_factor = 0                    # Это последняя итерация "while"
                                    break                               # Прерываем список "ping status"
                        curr_index += index_factor  # ...ищем дальше
                        iteration += 1
                        if iteration >= len(current_ring_list)+1:
                            break

                if successor_name:       # После того, как нашли "преемника"...
                    lprint(f"Преемник: {successor_name}")

                    # Кольцо в любом случае имеет разворот, так как найден "преемник"
                    # Необходимо установить admin down в сторону "поворота" кольца
                    if rotate == 'positive':
                        i = 1
                    else:
                        i = -1

                    successor_to = double_current_ring_list[current_ring_list.index(successor_name) + i]
                    successor_intf = find_port_by_desc(current_ring, successor_name, successor_to)

                    status_before = ''
                    for device in current_ring_list:
                        for dev_name, status in devices_ping:
                            if device == dev_name and not bool(findall('SSW', device)):
                                if status:
                                    status_before += ' ' * 10 + f'доступно   {device}\n'
                                else:
                                    status_before += ' ' * 10 + f'недоступно {device}\n'

                    email.send_text(subject=f'Начинаю разворот кольца {current_ring_name}',
                                    text=f'Состояние кольца до разворота: \n {status_before}'
                                         f'\nБудут выполнены следующие действия:'
                                         f'\nЗакрываем порт {successor_intf} на {successor_name}'
                                         f'\nПоднимаем порт {admin_down["interface"][0]} на {admin_down["device"]}')

                    # -----------------------------Закрываем порт на преемнике------------------------------------------
                    try_to_set_port = 2
                    while try_to_set_port > 0:
                        lprint(f'Закрываем порт {successor_intf} на {successor_name}')
                        operation_port_down = set_port_status(current_ring=current_ring,
                                                              device=successor_name,
                                                              interface=successor_intf,
                                                              status="down")
                        # Если поймали исключение, то пробуем еще один раз
                        if 'Exception' in operation_port_down and 'SAVE' not in operation_port_down:
                            try_to_set_port -= 1
                            if try_to_set_port > 1:
                                lprint('\nПробуем еще один раз закрыть порт\n')
                            continue
                        break

                    # ---------------------------Если порт на преемнике НЕ закрыли--------------------------------------
                    if operation_port_down == 'telnet недоступен':
                        email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                        text=f'Не удалось подключиться к {successor_name} по telnet!'
                                             f'({current_ring[successor_name]["ip"]})')

                    elif operation_port_down == 'неверный логин или пароль':
                        email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                        text=f'Не удалось зайти на оборудование {successor_name}'
                                             f'({current_ring[successor_name]["ip"]}) {operation_port_down}')

                    elif operation_port_down == 'cant set down':
                        email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                        text=f'На оборудовании {successor_name} ({current_ring[successor_name]["ip"]})'
                                             f'не удалось закрыть порт {successor_intf}!')

                    elif operation_port_down == 'cant status':
                        email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                        text=f'На оборудовании {successor_name} ({current_ring[successor_name]["ip"]})'
                                             f'была послана команда закрыть порт {successor_intf}, но '
                                             f'не удалось распознать интерфейсы для проверки его состояния(см. логи)\n'
                                             f'Отправлена команда на возврат порта в прежнее состояние (up)')

                    elif 'DONT SAVE' in operation_port_down:
                        # открываем порт
                        try_to_set_port = 2
                        while try_to_set_port > 0:
                            lprint(f'Открываем порт {successor_intf} на {successor_name}')
                            operation_port_up = set_port_status(current_ring=current_ring,
                                                                device=successor_name,
                                                                interface=successor_intf,
                                                                status="up")
                            # Если поймали исключение, то пробуем еще один раз
                            if 'Exception' in operation_port_up and 'SAVE' not in operation_port_up:
                                try_to_set_port -= 1
                                if try_to_set_port > 1:
                                    lprint('\nПробуем еще один раз открыть порт\n')
                                continue
                            break
                        if operation_port_up == 'DONE' or 'DONT SAVE' in operation_port_up:
                            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                            text=f'На оборудовании {successor_name} ({current_ring[successor_name]["ip"]})'
                                                 f'после закрытия порта {successor_intf} не удалось сохранить '
                                                 f'конфигурацию!\nВернул порт в исходное состояние (up)\n'
                                                 f'Разворот кольца прерван')
                        else:
                            email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                            text=f'На оборудовании {successor_name} ({current_ring[successor_name]["ip"]})'
                                                 f'после закрытия порта {successor_intf} не удалось сохранить '
                                                 f'конфигурацию!\nПопытка поднять порт обратно закончилась неудачей: '
                                                 f'{operation_port_up}.\n'
                                                 f'Разворот кольца прерван')
                        delete_ring_from_deploying_list(current_ring_name)
                        sys.exit()
                        # Выход

                    elif operation_port_down == 'Exception: cant set port status':
                        email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                        text=f'Возникло прерывание в момент закрытия порта {successor_intf} '
                                             f'на оборудовании {successor_name} ({current_ring[successor_name]["ip"]})')

                    elif 'Exception' in operation_port_down:
                        email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                        text=f'Возникло прерывание после подключения к оборудованию '
                                             f'{successor_name} ({current_ring[successor_name]["ip"]})')

                    # ------------------------------------Если порт закрыли---------------------------------------------
                    elif operation_port_down == 'DONE':

                        # ---------------------Поднимаем порт на admin_down_device--------------------------------------
                        lprint(f'Поднимаем порт {admin_down["interface"][0]} на {admin_down["device"]}')
                        operation_port_up = set_port_status(current_ring=current_ring,
                                                            device=admin_down['device'],
                                                            interface=admin_down['interface'][0],
                                                            status="up")

                        # Если проблема возникла до стадии сохранения
                        if 'SAVE' not in operation_port_up and 'DONE' not in operation_port_up:
                            # Восстанавливаем порт на преемнике в исходное состояние (up)
                            lprint(f'\nВосстанавливаем порт {successor_intf} на {successor_name} в исходное состояние (up)\n')
                            operation_port_reset = set_port_status(current_ring=current_ring,
                                                                   device=successor_name,
                                                                   interface=successor_intf,
                                                                   status="up")
                            if operation_port_reset == 'DONE':
                                email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                                text=f'Были приняты попытки развернуть кольцо {current_ring_name}\n'
                                                     f'В процессе выполнения был установлен статус порта '
                                                     f'{successor_intf} у {successor_name} "admin down", '
                                                     f'а затем возникла ошибка: {operation_port_up} на узле '
                                                     f'{admin_down["device"]} в попытке поднять порт '
                                                     f'{admin_down["interface"][0]}\nДалее порт {successor_intf} '
                                                     f'на {successor_name} был возвращен в исходное состояние (up)')
                            # Если проблема возникла до стадии сохранения
                            elif 'SAVE' not in operation_port_reset:
                                email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                                text=f'Были приняты попытки развернуть кольцо {current_ring_name}\n'
                                                     f'В процессе выполнения был установлен статус порта '
                                                     f'{successor_intf} у {successor_name} "admin down", '
                                                     f'а затем возникла ошибка: {operation_port_up} на узле '
                                                     f'{admin_down["device"]} в попытке поднять порт '
                                                     f'{admin_down["interface"][0]}\nДалее возникла ошибка в процессе '
                                                     f'возврата порта {successor_intf} на {successor_name} в '
                                                     f'исходное состояние (up) \nError: {operation_port_reset}')
                            # Если проблема возникла на стадии сохранения
                            elif 'SAVE' in operation_port_reset:
                                email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                                text=f'Были приняты попытки развернуть кольцо {current_ring_name}\n'
                                                     f'В процессе выполнения был установлен статус порта '
                                                     f'{successor_intf} у {successor_name} "admin down", '
                                                     f'а затем возникла ошибка: {operation_port_up} на узле '
                                                     f'{admin_down["device"]} в попытке поднять порт '
                                                     f'{admin_down["interface"][0]}\nДалее порт {successor_intf} '
                                                     f'на {successor_name} был возвращен в исходное состояние (up), '
                                                     f'но на стадии сохранения возникла ошибка: {operation_port_reset}'
                                                     f'\nПроверьте и сохраните конфигурацию!')
                            delete_ring_from_deploying_list(current_ring_name)
                            sys.exit()

                        # Если проблема возникла во время стадии сохранения
                        elif 'SAVE' in operation_port_up:
                            email.send_text(subject=f'{current_ring_name} Автоматический разворот кольца FTTB',
                                            text=f'Развернуто кольцо'
                                                 f'\nДействия: '
                                                 f'\n1)  На {successor_name} порт {successor_intf} - "admin down" '
                                                 f'в сторону узла {successor_to}\n'
                                                 f'2)  На {admin_down["device"]} порт {admin_down["interface"]} '
                                                 f'- "up" в сторону узла {admin_down["next_device"]}\n')
                            delete_ring_from_deploying_list(current_ring_name)
                            sys.exit()

                        # --------------------------------Порт подняли-----------------------------
                        elif operation_port_up == 'DONE':
                            wait_step = 2
                            all_avaliable = 0
                            while wait_step > 0:
                                # Ждем 50 секунд
                                lprint('Ожидаем 50 сек, не прерывать\n'
                                      '0                       25                       50с')
                                time_sleep(50)
                                # Пингуем заново все устройства в кольце с агрегации
                                new_ping_status = ping_from_device(current_ring_list[0], current_ring)
                                for _, available in new_ping_status:
                                    if not available:
                                        break  # Если есть недоступное устройство
                                else:
                                    lprint("Все устройства в кольце после разворота доступны!\n")
                                    all_avaliable = 1  # Если после разворота все устройства доступны
                                if all_avaliable or wait_step == 1:
                                    break
                                # Если по истечении 50с остались недоступные устройства, то ждем еще 50с
                                wait_step -= 1

                            # После разворота остались недоступными некоторые устройства
                            if not all_avaliable:
                                # Разворот выполнен!
                                with open(f'{root_dir}/rotated_rings.yaml', 'r') as rings_yaml:  # Чтение файла
                                    ring_to_save = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                                ring_to_save[current_ring_name] = {"default_host": admin_down['device'],
                                                                   "default_port": admin_down['interface'][0],
                                                                   "default_to": admin_down['next_device'][0],
                                                                   "admin_down_host": successor_name,
                                                                   "admin_down_port": successor_intf,
                                                                   "admin_down_to": successor_to,
                                                                   "priority": 1}
                                with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
                                    yaml.dump(ring_to_save, save_ring, default_flow_style=False)
                                # Отправка e-mail
                                email.send(current_ring_name, current_ring_list, devices_ping, new_ping_status,
                                           successor_name, successor_intf, successor_to,
                                           admin_down['device'], admin_down['interface'][0],
                                           admin_down['next_device'][0])
                                lprint("Отправлено письмо!")
                                sys.exit()

                            # Если на втором проходе у нас при развороте кольца, снова все узлы доступны, то
                            # это обрыв кабеля, в таком случае оставляем кольцо в развернутом виде
                            if this_is_the_second_loop:
                                lprint(f"Проблема вероятнее всего находится между {successor_name} и {successor_to}")
                                with open(f'{root_dir}/rotated_rings.yaml', 'r') as rings_yaml:  # Чтение файла
                                    ring_to_save = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                                ring_to_save[current_ring_name] = {"default_host": admin_down['device'],
                                                                   "default_port": admin_down['interface'][0],
                                                                   "default_to": admin_down['next_device'][0],
                                                                   "admin_down_host": successor_name,
                                                                   "admin_down_port": successor_intf,
                                                                   "admin_down_to": successor_to,
                                                                   "priority": 2}
                                with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
                                    yaml.dump(ring_to_save, save_ring, default_flow_style=False)

                                # Отправка e-mail
                                info = f'Возможен обрыв кабеля между {successor_name} и ' \
                                       f'{double_current_ring_list[current_ring_list.index(successor_name) + i]}\n'

                                email.send(ring_name=current_ring_name,
                                           current_ring_list=current_ring_list,
                                           old_devices_ping=devices_ping,
                                           new_devices_ping=new_ping_status,
                                           admin_down_host=successor_name,
                                           admin_down_port=successor_intf,
                                           admin_down_to=successor_to,
                                           up_host=admin_down['device'],
                                           up_port=admin_down['interface'][0],
                                           up_to=admin_down['next_device'][0],
                                           info=info)
                                lprint("Отправлено письмо!")
                                sys.exit()

                            # Если после разворота все узлы сети доступны, то это может быть обрыв кабеля, либо
                            #   временное отключение электроэнергии. Разворачиваем кольцо в исходное состояние,
                            #   чтобы определить какой именно у нас случай
                            lprint("Возможен обрыв кабеля, либо временное отключение электроэнергии. \n"
                                   "Разворачиваем кольцо в исходное состояние, "
                                   "чтобы определить какой именно у нас случай")
                            try_to_set_port2 = 2
                            # ------------------Закрываем порт на admin_down_device
                            while try_to_set_port2 > 0:
                                lprint(f'Закрываем порт {admin_down["interface"][0]} на {admin_down["device"]}')
                                operation_port_down2 = set_port_status(current_ring=current_ring,
                                                                       device=admin_down['device'],
                                                                       interface=admin_down['interface'][0],
                                                                       status="down")
                                # Если возникло прерывание до стадии сохранения, то пытаемся закрыть порт еще раз
                                if try_to_set_port2 == 2 and 'Exception' in operation_port_down2 \
                                        and 'SAVE' not in operation_port_down2:
                                    try_to_set_port2 -= 1
                                    # Пингуем заново все устройства в кольце
                                    ping_stat = ping_devices(current_ring)
                                    for _, available in ping_stat:
                                        if not available:
                                            break   # Если есть недоступное устройство
                                    else:
                                        continue    # Если все устройства доступны, то пробуем закрыть порт еще раз
                                break       # Выход из цикла

                            # ------------------------Неудача
                            if operation_port_down2 == 'telnet недоступен':
                                info = f'В попытке определить был ли это обрыв кабеля, либо временное отключение ' \
                                       f'электроэнергии не удалось подключиться по telnet к {admin_down["device"]}!'

                            elif operation_port_down2 == 'неверный логин или пароль':
                                info = f'В попытке определить был ли это обрыв кабеля, либо временное отключение ' \
                                       f'электроэнергии произошла ошибка "неверный логин или пароль" на ' \
                                       f'{admin_down["device"]} ({current_ring[admin_down["device"]]["ip"]})\n' \
                                       f'Просьба разобраться, так как пару минут назад был ' \
                                       f'выполнен вход на это оборудование под тем же логином и паролем'

                            elif operation_port_down2 == 'cant set down':
                                info = f'В попытке определить был ли это обрыв кабеля, либо временное отключение ' \
                                       f'электроэнергии не удалось развернуть кольцо обратно: \n' \
                                       f'порт {admin_down["interface"][0]} ({current_ring[admin_down["device"]]["ip"]}) ' \
                                       f'на оборудовании {admin_down["device"]}' \
                                       f'не был установлен в состояние admin down!'

                            elif 'Exception' in operation_port_down2 and 'SAVE' not in operation_port_down2:
                                info = f'В попытке определить был ли это обрыв кабеля, либо временное отключение ' \
                                       f'электроэнергии не удалось развернуть кольцо обратно: \n' \
                                       f'возникло прерывание при работе с оборудованием {admin_down["device"]} ' \
                                       f'({current_ring[admin_down["device"]]["ip"]})' \
                                       f'во время закрытия порта {admin_down["interface"][0]}'

                            # ------------------------Порт закрыт либо не сохранена конфигурация
                            elif operation_port_down2 == 'DONE' or 'DONT SAVE' in operation_port_down2:

                                # --- Если порт закрыт
                                if operation_port_down2 == 'DONE':
                                    # --------------------Открываем порт на преемнике
                                    lprint(f'Поднимаем порт {successor_intf} на {successor_name}')
                                    operation_port_up2 = set_port_status(current_ring=current_ring,
                                                                         device=successor_name,
                                                                         interface=successor_intf,
                                                                         status="up")

                                    # ----------------------Порт открыт
                                    if operation_port_up2 == 'DONE':
                                        wait_step = 2
                                        all_avaliable = 0
                                        while wait_step > 0:
                                            # Ждем 50 секунд
                                            lprint('Ожидаем 50 сек, не прерывать\n'
                                                   '0                       25                       50с')
                                            time_sleep(50)
                                            # Пингуем заново все устройства в кольце с агрегации
                                            new_ping_status = ping_from_device(current_ring_list[0], current_ring)
                                            for _, available in new_ping_status:
                                                if not available:
                                                    break  # Если есть недоступное устройство
                                            else:
                                                lprint("Все устройства в кольце после разворота доступны!\n")
                                                all_avaliable = 1  # Если после разворота все устройства доступны
                                            # Если по истечении 50с остались недоступные устройства, то ждем еще 50с
                                            if all_avaliable or wait_step == 1:
                                                break
                                            wait_step -= 1

                                        if all_avaliable:
                                            # Если все узлы доступны, то исключаем обрыв кабеля и оставляем кольцо в
                                            #   исходном состоянии. Разворот не требуется!
                                            delete_ring_from_deploying_list(current_ring_name)
                                            lprint(f"Все узлы в кольце доступны, разворот не потребовался!\n"
                                                  f"Узел {admin_down['device']}, состояние порта {admin_down['interface'][0]}: "
                                                  f"admin down в сторону узла {admin_down['next_device'][0]}")
                                            email.send_text(subject=f'{current_ring_name} Автоматический разворот '
                                                                    f'кольца FTTB',
                                                            text=f"Все узлы в кольце доступны, разворот не потребовался!\n"
                                                                 f"Узел {admin_down['device']}, состояние порта "
                                                                 f"{admin_down['interface'][0]}: admin down в сторону "
                                                                 f"узла {admin_down['next_device'][0]}")
                                            delete_ring_from_deploying_list(current_ring_name)
                                            sys.exit()
                                            # Выход

                                        elif not all_avaliable:
                                            # Если есть недоступные узлы, то необходимо выполнить проверку кольца заново
                                            main(new_ping_status, current_ring, current_ring_list, current_ring_name,
                                                 this_is_the_second_loop=True)
                                            sys.exit()
                                            # Выход

                                # ---------------------порт открыт, но конфигурация не сохранена
                                # ----------------------Порт не открыт
                                lprint(f'Возвращаем закрытый раннее порт {admin_down["interface"][0]} на '
                                       f'{admin_down["device"]} в прежнее состояние (up)')
                                # Поднимаем закрытый раннее порт
                                operation_port_reset2 = set_port_status(current_ring=current_ring,
                                                                        device=admin_down['device'],
                                                                        interface=admin_down['interface'][0],
                                                                        status="up")

                                if operation_port_reset2 == 'DONE' and operation_port_down2 == 'DONE':
                                    new_ping_status = ping_from_device(current_ring_list[0], current_ring)
                                    info = f'После разворота стали доступны все устройства и чтобы определить, ' \
                                           f'либо это скачек электроэнергии, либо обрыв, была предпринята попытка ' \
                                           f'развернуть кольцо обратно. Для этого на узле сети {admin_down["device"]}' \
                                           f' был положен порт {admin_down["interface"][0]}, а затем возникла ошибка ' \
                                           f'при поднятии порта {successor_intf} у оборудования {successor_name}\n' \
                                           f' {operation_port_up2}\nЗатем вернули порт {admin_down["interface"][0]} ' \
                                           f'узла {admin_down["device"]} в состояние up.'

                                if operation_port_reset2 == 'DONE' and 'DONT SAVE' in operation_port_down2:
                                    new_ping_status = ping_from_device(current_ring_list[0], current_ring)
                                    info = f'После разворота стали доступны все устройства и чтобы определить, ' \
                                           f'либо это скачек электроэнергии, либо обрыв, была предпринята попытка ' \
                                           f'развернуть кольцо обратно. Для этого на узле сети {admin_down["device"]}' \
                                           f' был положен порт {admin_down["interface"][0]}, а затем возникла ошибка ' \
                                           f'в сохранении конфигурации: {operation_port_down2}\n' \
                                           f' Затем вернули порт {admin_down["interface"][0]} ' \
                                           f'узла {admin_down["device"]} в состояние up.'

                                if operation_port_reset2 != 'DONE' and operation_port_down2 == 'DONE':
                                    new_ping_status = ping_from_device(current_ring_list[0], current_ring)
                                    info = f'После разворота стали доступны все устройства и чтобы определить, ' \
                                           f'либо это скачек электроэнергии, либо обрыв, была предпринята попытка ' \
                                           f'развернуть кольцо обратно. Для этого на узле сети {admin_down["device"]}' \
                                           f' был положен порт {admin_down["interface"][0]}, а затем возникла ошибка ' \
                                           f'при поднятии порта {successor_intf} у оборудования {successor_name}\n' \
                                           f' {operation_port_up2}\nЗатем возникла ошибка во время поднятия порта ' \
                                           f'{admin_down["interface"][0]} на оборудовании {admin_down["device"]}\n' \
                                           f'{operation_port_reset2}'

                                if operation_port_reset2 != 'DONE' and operation_port_down2 != 'DONE':
                                    new_ping_status = ping_from_device(current_ring_list[0], current_ring)
                                    info = f'После разворота стали доступны все устройства и чтобы определить, ' \
                                           f'либо это скачек электроэнергии, либо обрыв, была предпринята попытка ' \
                                           f'развернуть кольцо обратно. Для этого на узле сети {admin_down["device"]}' \
                                           f' был положен порт {admin_down["interface"][0]}, но возникла ошибка ' \
                                           f'в сохранении конфигурации: {operation_port_down2}\nЗатем ' \
                                           f'возникла ошибка во время поднятия порта ' \
                                           f'{admin_down["interface"][0]} на оборудовании {admin_down["device"]}\n' \
                                           f'{operation_port_reset2}'

                            # Сохраняем статус разворота
                            with open(f'{root_dir}/rotated_rings.yaml', 'r') as rings_yaml:  # Чтение файла
                                ring_to_save = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                            ring_to_save[current_ring_name] = {"default_host": admin_down['device'],
                                                               "default_port": admin_down['interface'][0],
                                                               "default_to": admin_down['next_device'][0],
                                                               "admin_down_host": successor_name,
                                                               "admin_down_port": successor_intf,
                                                               "admin_down_to": successor_to,
                                                               "priority": 1}
                            with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
                                yaml.dump(ring_to_save, save_ring, default_flow_style=False)
                            # Отправка e-mail
                            email.send(ring_name=current_ring_name,
                                       current_ring_list=current_ring_list,
                                       old_devices_ping=devices_ping,
                                       new_devices_ping=new_ping_status,
                                       admin_down_host=successor_name,
                                       admin_down_port=successor_intf,
                                       admin_down_to=successor_to,
                                       up_host=admin_down['device'],
                                       up_port=admin_down['interface'][0],
                                       up_to=admin_down['next_device'][0],
                                       info=info)
                            lprint("Отправлено письмо!")
                            sys.exit()

                    else:
                        email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                        text=f'Возникло что-то невозможное во время работы с оборудованием '
                                             f'{successor_name}! ({current_ring[successor_name]["ip"]}) 😵')
                    delete_ring_from_deploying_list(current_ring_name)
                    # Выход

                else:
                    lprint("Все узлы недоступны!")
                    delete_ring_from_deploying_list(current_ring_name)
                break
    else:                                                       # Если все устройства недоступны по "ping", то...
        lprint("Все узлы сети из данного кольца недоступны!")        # ...конец кольца


def start(dev: str):
    get_ring_ = get_ring(dev, rings_files)
    if not get_ring_:
        sys.exit()
    current_ring, current_ring_list, current_ring_name = get_ring_

    # Заголовок
    lprint('\n')
    lprint('-' * 20 + 'NEW SESSION' + '-' * 20)
    lprint(' ' * 12 + str(datetime.now()))
    lprint(' ' * ((51 - len(dev)) // 2) + dev + ' ' * ((51 - len(dev)) // 2))
    lprint('-' * 51)

    with open(f'{root_dir}/rotated_rings.yaml', 'r') as rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
        if rotated_rings:
            for rring in rotated_rings:
                if current_ring_name == rring:
                    lprint(f"Кольцо, к которому принадлежит узел сети {dev} уже находится в списке как развернутое\n"
                           f"(смотреть файл \"{root_dir}/rotated_rings.yaml\")")
                    return False

    devices_ping = ping_devices(current_ring)

    for _, available in devices_ping:
        if not available:
            break
    else:
        lprint("Все устройства в кольце доступны, разворот не требуется!")
        return False

    for _, available in devices_ping:
        if available:
            break
    else:
        lprint("Все устройства в кольце недоступны, разворот невозможен!")
        return False

    main(devices_ping, current_ring, current_ring_list, current_ring_name)


def time_sleep(sec: int) -> None:
    '''
    Пауза с выводом вертикальной линии в одну строку, равную количеству секунд ожидания \n
    :param sec: время в секундах
    :return: None
    '''
    for s in range(sec):
        print('|', end='', flush=True)
        time.sleep(1)
    lprint('\n')


# Функции для ключевых слов


def print_help():
    print('''
Usage:  motr.py [-D DEVICE [OPTIONS]]
        motr.py [--device DEVICE [OPTIONS]]
        
    -D, --device     Device name
    
        --check         Search admin down on each devices in ring
        --check-des     Checks if the description on the interfaces 
                        of each devices contains names two device by side
        --show-int      Show interfaces of device
        --show-all      Show interfaces of all devices in ring
        --show-ping     Show ping

Options:
    --conf          Show config file path and variables
    --stat          Show information about rings
    ''')


def check_descriptions(ring: dict, dev_list: list) -> bool:
    valid = True

    def neigh(ring: dict, device: str, double_list: list):
        intf = interfaces(ring, device, enable_print=False)
        for line in intf:
            if bool(findall(double_list[double_list.index(device) - 1], line[2])):
                result[device]['top'] = f'\033[33m{double_list[double_list.index(device) - 1]}\033[0m'
            if bool(findall(double_list[double_list.index(device) + 1], line[2])):
                result[device]['bot'] = f'\033[33m{double_list[double_list.index(device) + 1]}\033[0m'

    result = {dev: {'top': '', 'bot': ''} for dev in dev_list}
    double_list = dev_list + dev_list

    with ThreadPoolExecutor(max_workers=10) as executor:
        for device in dev_list:
            valid = executor.submit(neigh, ring, device, double_list)

    for res_dev in result:
        print(f'\nОборудование: \033[34m{res_dev}\033[0m {ring[res_dev]["ip"]}')
        print(f'    Сосед сверху: {result[res_dev]["top"]}')
        print(f'    Сосед снизу: {result[res_dev]["bot"]}')
        if not result[res_dev]["top"] or not result[res_dev]["bot"]:
            valid = False
    return valid


def show_all_int(device: str):

    def get_interface(ring: dict, dev: str):
        result[dev] = interfaces(ring, dev, enable_print=False)

    get_ring_ = get_ring(device, rings_files)
    if not get_ring_:
        sys.exit()
    ring, ring_list, ring_name = get_ring_
    print(f'    \033[32m{ring_name}\033[0m\n')
    ping_devices(ring)
    result = {x: [] for x in ring_list}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for device in ring_list:
            executor.submit(get_interface, ring, device)
    for d in result:
        print(f'\nОборудование: \033[34m{d}\033[0m {ring[d]["ip"]}')
        try:
            print(tabulate(tuple(result[d]), headers=['\nInterface', 'Admin\nStatus', '\nDescription']))
        except TypeError:
            print(result[d])


def check_admin_down(device: str):

    def get_ad(ring, ring_list, device):
        output_check[device] = search_admin_down(ring, ring_list, device, enable_print=False)

    get_ring_ = get_ring(device, rings_files)
    if not get_ring_:
        sys.exit()
    ring, ring_list, ring_name = get_ring_
    print(f'    \033[32m{ring_name}\033[0m\n')
    devices_ping = ping_devices(ring)
    with ThreadPoolExecutor(max_workers=10) as executor:
        output_check = {x: () for x in ring_list}
        for device in ring_list:
            for d, s in devices_ping:
                if device == d and s:
                    executor.submit(get_ad, ring, ring_list, device)
    for d in output_check:
        print(f'\nОборудование: \033[34m{d}\033[0m {ring[d]["ip"]}')
        if output_check[d]:
            print(f'\033[32mFind admin down!\033[0m Интерфейс: \033[32m{output_check[d]["interface"][0]}\033[0m '
                  f'ведет к устройству \033[32m{output_check[d]["next_device"][0]}\033[0m')
        else:
            print('\033[33mNo admin down\033[0m')


if __name__ == '__main__':

    if len(sys.argv) == 1:
        print_help()
        sys.exit()

    rings_files = get_config('rings_directory')
    email_notification = get_config('email_notification')

    from validation import validation  # Проверка файлов колец на валидность

    for i, key in enumerate(sys.argv):
        if key == '-h' or key == '--help':
            print_help()

        if key == '--stat':
            rings_count = 0
            devices_count = 0
            for file in rings_files:
                with open(file, 'r') as ff:
                    rings = yaml.safe_load(ff)  # Перевод из yaml в словарь
                rings_count += len(rings)
                devrc = 0
                for r in rings:
                    devrc += len(rings[r])
                devices_count += devrc
                print(f'rings: {len(rings)} devices: {devrc:<4} in file: {file}')
            print(f"\n\033[4mTotal rings count\033[0m:\033[0m \033[32m{rings_count}\033[0m"
                  f"\n\033[4mTotal devices count\033[0m: \033[32m{devices_count}\033[0m")
            with open(f'{root_dir}/rotated_rings.yaml', 'r') as r_rings_yaml:
                r_rings = yaml.safe_load(r_rings_yaml)
            deploying_rings = [x for x in r_rings if r_rings[x] == 'Deploying']
            r_rings = [x for x in r_rings]
            r_rings = set(r_rings) - set(deploying_rings)
            print(f'\n\033[4mDeploying rings\033[0m: \033[32m{len(deploying_rings)}\033[0m')
            for line in deploying_rings:
                print(line)
            print(f'\n\033[4mRotated rings\033[0m: \033[32m{len(r_rings)-1}\033[0m')
            for line in r_rings:
                if line:
                    print(line)

        if key == '--conf':
            if not os.path.exists(f'{root_dir}/config.conf'):
                set_default_config()
            print(f'Файл конфигурации: \033[32m{root_dir}/config.conf\033[0m\n')
            print('[\033[32mSettings\033[0m]')
            print(f'    email_notification = {get_config("email_notification")}')
            rd = get_config('rings_directory')
            print(f'    rings_directory = {rd[0]}')
            for d in rd[1:]:
                print(' '*22+d)
            print('\n[\033[32mEmail\033[0m]')
            to_addr = get_config("to_address").split(',')
            print(f'    to_address = \033[35m{to_addr[0].split("@")[0]}\033[37m@{to_addr[0].split("@")[1]}\033[0m')
            for addr in to_addr[1:]:
                print(' '*16 + f'\033[35m{addr.split("@")[0]}\033[37m@{addr.split("@")[1]}\033[0m')
            print()

        if (key == '-D' or key == '--device') and validation(rings_files):
            if len(sys.argv) > i+1:
                if len(sys.argv) > i+2 and sys.argv[i+2] == '--check':
                    check_admin_down(sys.argv[i + 1])

                elif len(sys.argv) > i+2 and sys.argv[i+2] == '--show-all':
                    show_all_int(sys.argv[i + 1])

                elif len(sys.argv) > i+2 and sys.argv[i+2] == '--show-int':
                    get_ring_ = get_ring(sys.argv[i + 1], rings_files)
                    if not get_ring_:
                        sys.exit()
                    ring, _, ring_name = get_ring_
                    print(f'    \033[32m{ring_name}\033[0m\n')
                    print(tabulate(interfaces(ring, sys.argv[i+1]),
                                   headers=['\nInterface', 'Admin\nStatus', '\nDescription']))

                elif len(sys.argv) > i+2 and sys.argv[i+2] == '--check-des':
                    get_ring_ = get_ring(sys.argv[i + 1], rings_files)
                    if not get_ring_:
                        sys.exit()
                    ring, ring_list, ring_name = get_ring_
                    print(f'    \033[32m{ring_name}\033[0m\n')
                    ping_devices(ring)
                    if check_descriptions(ring, ring_list):
                        print('\n\033[32m Проверка пройдена успешно - OK!\033[0m')
                    else:
                        print('\n\033[31m Проверьте descriptions - Failed!\033[0m')

                elif len(sys.argv) > i+2 and sys.argv[i+2] == '--show-ping':
                    get_ring_ = get_ring(sys.argv[i + 1], rings_files)
                    if not get_ring_:
                        sys.exit()
                    ring, ring_list, ring_name = get_ring_
                    ping_devices(ring)

                else:
                    start(sys.argv[i+1])
            else:
                print_help()
