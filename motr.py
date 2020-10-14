#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from concurrent.futures import ThreadPoolExecutor
import pexpect
import yaml
import re
from re import findall
import textfsm
import sys
import os
import subprocess
from datetime import datetime
import time
import email_notifications as email
import configparser
from tabulate import tabulate

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])
email_notification = 'enable'
rings_files = []


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


def get_ring(device_name: str) -> tuple:
    '''
    Функция для поиска кольца, к которому относится переданный узел сети \n
    :param device_name: Уникальное имя узла сети
    :return: 1 Кольцо (dict),
             2 Узлы сети в кольце (list)
             3 Имя кольца (str)
    '''
    print('---- def get_ring ----')
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


def ping_from_device(device: str, ring: dict):
    '''
    Заходим на оборудование через telnet и устанавливаем состояние конкретного порта
    :param ring"    Кольцо
    :param device:          Имя узла сети, с которым необходимо взаимодействовать
    :return:                В случае успеха возвращает 1, неудачи - 0
    '''
    with pexpect.spawn(f"telnet {ring[device]['ip']}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                print("    Telnet недоступен!")
                return False
            telnet.sendline(ring[device]["user"])
            print(f"    Login to {device}")
            telnet.expect("[Pp]ass")
            telnet.sendline(ring[device]["pass"])
            print(f"    Pass to {device}")
            match = telnet.expect([']', '>', '#', 'Failed to send authen-req'])
            if match == 3:
                print('    Неверный логин или пароль!')
                return False
            telnet.sendline('show version')
            version = ''
            while True:
                m = telnet.expect([']', '-More-', '>', '#'])
                version += str(telnet.before.decode('utf-8'))
                if m == 1:
                    telnet.sendline(' ')
                else:
                    break

            devices_status = [(device, True)]
            print(f'Доступно   {device}')
            for dev in ring:
                if device != dev:
                    try:
                        telnet.sendline(f'ping {ring[dev]["ip"]}')

                        # Huawei
                        if bool(findall(r'Error: Unrecognized command', version)):
                            match = telnet.expect(['Request time out', 'Error', 'Reply from'])
                        # Cisco
                        elif bool(findall(r'Cisco IOS', version)):
                            match = telnet.expect(['is 0 percent', 'Unrecognized host', 'is 100 percent'])
                        # D-Link
                        elif bool(findall(r'Next possible completions:', version)):
                            match = telnet.expect(['Request timed out', 'Command: ping', 'Reply from'])
                        # Alcatel, Linksys
                        elif bool(findall(r'SW version', version)):
                            pass
                        # Eltex
                        elif bool(findall(r'Active-image: ', version)):
                            match = telnet.expect(['PING: timeout', 'Host not found', 'bytes from'])
                        # Если не был определен вендор, то возвращаем False
                        else:
                            telnet.sendline('exit')
                            return False

                        if match < 2:
                            telnet.sendcontrol('c')
                            devices_status.append((dev, False))
                            print(f'Недоступно {dev}')
                        elif match == 2:
                            telnet.sendcontrol('c')
                            devices_status.append((dev, True))
                            print(f'Доступно   {dev}')
                        telnet.expect([']', '>', '#'])
                    except pexpect.exceptions.TIMEOUT:
                        devices_status.append((dev, False))
                        print(f'Недоступно {dev} Exception: timeout')
                        telnet.sendcontrol('c')
                        telnet.expect([']', '>', '#'])

            # Huawei
            if bool(findall(r'Error: Unrecognized command', version)):
                telnet.sendline('quit')
            # Cisco
            elif bool(findall(r'Cisco IOS', version)):
                telnet.sendline('exit')
            # D-Link
            elif bool(findall(r'Next possible completions:', version)):
                telnet.sendline('logout')
            # Alcatel, Linksys
            elif bool(findall(r'SW version', version)):
                telnet.sendline('exit')
            # Eltex
            elif bool(findall(r'Active-image: ', version)):
                telnet.sendline('exit')

            return devices_status           # Возвращаем список

        except pexpect.exceptions.TIMEOUT:
            print("    Время ожидания превышено! (timeout)")
            return False


def ping_devices(ring: dict):
    '''
    Функция определяет, какие из узлов сети в кольце доступны по "ping" \n
    :param ring: Кольцо
    :return: Двумерный список: имя узла и его статус "True" - ping успешен, "False" - нет
    '''
    status = []
    print("---- def ring_ping_status ----")

    def ping(ip, device):
        result = subprocess.run(['ping', '-c', '3', '-n', ip], stdout=subprocess.DEVNULL)
        if not result.returncode:  # Проверка на доступность: 0 - доступен, 1 и 2 - недоступен
            status.append((device, True))
            print(f"    \033[32mTrue\033[0m    \033[34m{device}\033[0m")
        else:
            status.append((device, False))
            print(f"    \033[31m\033[5mFalse\033[0m   {device}")

    with ThreadPoolExecutor(max_workers=10) as executor:    # Многопоточность
        for device in ring:
            executor.submit(ping, ring[device]['ip'], device)   # Запускаем фунцию ping и передаем ей переменные

    return status


def delete_ring_from_deploying_list(ring_name):
    with open(f'{root_dir}/rotated_rings.yaml', 'r') as rotated_rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rotated_rings_yaml)  # Перевод из yaml в словарь
        del rotated_rings[ring_name]
    with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
        yaml.dump(rotated_rings, save_ring, default_flow_style=False)  # Переписываем файл


def validation(files: list) -> bool:
    '''
    Проверяет структуру файлов колец и возвращает True, когда все файлы прошли проверку и
    False, если хотя бы в одном файле найдено нарушение структуры \n
    :param files: список файлов
    :return: bool
    '''
    valid = [True for _ in range(len(files))]
    if not rings_files:
        print(f'Укажите в файле конфигурации {root_dir} файл с кольцами или папку')
        return False
    invalid_files = ''
    text = ''
    for num, file in enumerate(files):
        validation_text = ''
        try:
            with open(f'{file}', 'r') as rings_yaml:  # Чтение файла
                try:
                    rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                    if rings:
                        for ring in rings:
                            for dev in rings[ring]:
                                if len(dev.split()) > 1:
                                    validation_text += f'{ring} --> Имя узла сети должно быть записано в одно слово: {dev}\n'
                                    valid[num] = False
                                try:
                                    if not rings[ring][dev]['user']:
                                        validation_text += f'{ring} --> {dev} | не указан user\n'
                                        valid[num] = False
                                    if len(str(rings[ring][dev]['user']).split()) > 1:
                                        validation_text += f'{ring} --> {dev} | '\
                                                            f'user должен быть записан в одно слово: '\
                                                            f'{rings[ring][dev]["user"]}\n'
                                        valid[num] = False
                                except:
                                    validation_text += f'{ring} --> {dev} | не указан user\n'
                                    valid[num] = False

                                try:
                                    if not rings[ring][dev]['pass']:
                                        validation_text += f'{ring} --> {dev} | не указан пароль\n'
                                        valid[num] = False
                                    if len(str(rings[ring][dev]['pass']).split()) > 1:
                                        validation_text += f'{ring} --> {dev} | '\
                                                            f'пароль должен быть записан в одно слово: '\
                                                            f'{rings[ring][dev]["pass"]}\n'
                                        valid[num] = False
                                except:
                                    validation_text += f'{ring} --> {dev} | не указан пароль\n'
                                    valid[num] = False

                                try:
                                    if not rings[ring][dev]['ip']:
                                        validation_text += f'{ring} --> {dev} | не указан IP\n'
                                        valid[num] = False
                                    elif not bool(findall('\d{1,4}(\.\d{1,4}){3}', rings[ring][dev]['ip'])):
                                        validation_text += f'{ring} --> {dev} | '\
                                                            f'IP указан неверно: '\
                                                            f'{rings[ring][dev]["ip"]}\n'
                                        valid[num] = False
                                except:
                                    validation_text += f'{ring} --> {dev} | не указан IP\n'
                                    valid[num] = False
                    else:
                        validation_text += f'Файл "{root_dir}/check.yaml" пуст!\n'
                        valid[num] = False
                except Exception as e:
                    validation_text += str(e)
                    validation_text += '\nОшибка в синтаксисе!\n'
                    valid[num] = False
        except Exception as e:
            validation_text += str(e)
            valid[num] = False
        if not valid[num]:
            invalid_files += f'{file}\n'
            text += f'\n{file}\n{validation_text}'

    validation_text = ''
    valid_2 = True
    if not os.path.exists(f'{root_dir}/rotated_rings.yaml'):
        with open(f'{root_dir}/rotated_rings.yaml', 'w') as rr:
            rr.write("null: don't delete")
    try:
        with open(f'{root_dir}/rotated_rings.yaml', 'r') as rotated_rings_yaml:
            try:
                rotated_rings = yaml.safe_load(rotated_rings_yaml)
                if rotated_rings:
                    for ring in rotated_rings:
                        if not ring or rotated_rings[ring] == 'Deploying':
                            continue
                        try:
                            if not rotated_rings[ring]['admin_down_host']:
                                validation_text += f'{ring} --> не указан admin_down_host ' \
                                                   f'(узел сети, где порт в состоянии admin down)\n'
                                valid_2 = False
                            if len(str(rotated_rings[ring]['admin_down_host']).split()) > 1:
                                validation_text += f'{ring} --> admin_down_host должен быть записан в одно слово: '\
                                                    f'{rotated_rings[ring]["admin_down_host"]}\n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан admin_down_host ' \
                                               f'(узел сети, где порт в состоянии admin down)\n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['admin_down_port']:
                                validation_text += f'{ring} --> не указан admin_down_port ' \
                                                   f'(порт узла сети в состоянии admin down)/n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан admin_down_port ' \
                                               f'(порт узла сети в состоянии admin down)\n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['admin_down_to']:
                                validation_text += f'{ring} --> не указан admin_down_to '\
                                      f'(узел сети, который находится непосредственно за узлом,' \
                                                   f' у которого порт в состоянии admin down)\n'
                                valid_2 = False
                            if len(str(rotated_rings[ring]['admin_down_to']).split()) > 1:
                                validation_text += f'{ring} --> admin_down_to должен быть записан в одно слово: '\
                                                    f'{rotated_rings[ring]["admin_down_to"]}\n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан admin_down_to '\
                                  f'(узел сети, который находится непосредственно за узлом,' \
                                               f' у которого порт в состоянии admin down)\n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['default_host']:
                                validation_text += f'{ring} --> не указан default_host '\
                                      f'(узел сети, который должен иметь статус порта admin down по умолчанию)/n'
                                valid_2 = False
                            if len(str(rotated_rings[ring]['default_host']).split()) > 1:
                                validation_text += f'{ring} --> default_host должен быть записан в одно слово: '\
                                                    f'{rotated_rings[ring]["default_host"]}/n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан default_host '\
                                  f'(узел сети, который должен иметь статус порта admin down по умолчанию)/n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['default_port']:
                                validation_text += f'{ring} --> не указан default_port '\
                                      f'(порт узла сети, который должен иметь статус порта admin down по умолчанию)\n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан default_port '\
                                  f'(порт узла сети, который должен иметь статус порта admin down по умолчанию)\n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['default_to']:
                                validation_text += f'{ring} --> не указан default_to '\
                                      f'(узел сети, который находится непосредственно за узлом сети, '\
                                      f'который должен иметь статус порта admin down по умолчанию)\n'
                                valid_2 = False
                            if len(str(rotated_rings[ring]['default_to']).split()) > 1:
                                validation_text += f'{ring} --> default_to должен быть записан в одно слово: '\
                                                    f'{rotated_rings[ring]["default_to"]}\n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан default_to '\
                                                f'(узел сети, который находится непосредственно за узлом сети, '\
                                                f'который должен иметь статус порта admin down по умолчанию)\n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['priority']:
                                validation_text += f'{ring} --> не указан priority '
                                valid_2 = False
                            if not isinstance(rotated_rings[ring]['priority'], int):
                                validation_text += f'{ring} --> priority должен быть целочисленным числом: '\
                                                    f'{rotated_rings[ring]["priority"]}\n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан priority \n'
                            valid_2 = False
                else:
                    with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
                        save = {None: "don't delete"}
                        yaml.dump(save, save_ring, default_flow_style=False)
                    valid_2 = False
            except Exception as e:
                validation_text += str(e)
                validation_text += '\nОшибка в синтаксисе!\n'
                valid_2 = False
    except Exception as e:
        validation_text += str(e)
        valid_2 = False
    if not valid_2:
        invalid_files += f'{root_dir}/rotated_rings.yaml\n'
        text += f'\n{root_dir}/rotated_rings.yaml\n{validation_text}'

    for v in valid:
        if not v or not valid_2:
            if email_notification == 'enable':
                email.send_text('Разворот колец невозможен!',
                                f'Ошибка в структуре: \n'
                                f'{invalid_files}'
                                f'\n{text}')
            print(f'Ошибка в структуре: \n{invalid_files}\n{text}')
            return False
    return True


def main(devices_ping: list, current_ring: dict, current_ring_list: list, current_ring_name: str,
         this_is_the_second_loop: bool = False) -> None:

    successor_name = ''

    for device_name, device_status in devices_ping:     # Листаем узлы сети и их доступность по "ping"

        print('-'*51+'\n'+'-'*51)

        print(f"device_name: {device_name} | device_status: {device_status}")
        if device_status:                                   # Если нашли доступное устройство, то...
            admin_down = search_admin_down(current_ring, current_ring_list, device_name)    # ...ищем admin down
            if admin_down:                                  # 0 - host name, [1] - side host name, [2] - interface

                # Делаем отметку, что данное кольцо уже участвует в развороте
                with open(f'{root_dir}/rotated_rings.yaml', 'r') as rings_yaml:  # Чтение файла
                    rotated_rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                    rotated_rings[current_ring_name] = 'Deploying'
                with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
                    yaml.dump(rotated_rings, save_ring, default_flow_style=False)  # Переписываем файл

                print(f"Найден узел сети {admin_down['device']} со статусом порта {admin_down['interface'][0]}: "
                      f"admin down\nДанный порт ведет к {admin_down['next_device'][0]}")
                rotate = ring_rotate_type(current_ring_list, admin_down['device'], admin_down['next_device'][0])
                print(f'Разворот кольца: {rotate}')
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
                    print(f"Преемник: {successor_name}")

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
                        print(f'Закрываем порт {successor_intf} на {successor_name}')
                        operation_port_down = set_port_status(current_ring=current_ring,
                                                              device=successor_name,
                                                              interface=successor_intf,
                                                              status="down")
                        # Если поймали исключение, то пробуем еще один раз
                        if 'Exception' in operation_port_down and 'SAVE' not in operation_port_down:
                            try_to_set_port -= 1
                            if try_to_set_port > 1:
                                print('\nПробуем еще один раз закрыть порт\n')
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
                            print(f'Открываем порт {successor_intf} на {successor_name}')
                            operation_port_up = set_port_status(current_ring=current_ring,
                                                                device=successor_name,
                                                                interface=successor_intf,
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
                        print(f'Поднимаем порт {admin_down["interface"][0]} на {admin_down["device"]}')
                        operation_port_up = set_port_status(current_ring=current_ring,
                                                            device=admin_down['device'],
                                                            interface=admin_down['interface'][0],
                                                            status="up")

                        # Если проблема возникла до стадии сохранения
                        if 'SAVE' not in operation_port_up and 'DONE' not in operation_port_up:
                            # Восстанавливаем порт на преемнике в исходное состояние (up)
                            print(f'\nВосстанавливаем порт {successor_intf} на {successor_name} в исходное состояние (up)\n')
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
                                print('Ожидаем 50 сек, не прерывать\n'
                                      '0                       25                       50с')
                                time_sleep(50)
                                # Пингуем заново все устройства в кольце с агрегации
                                new_ping_status = ping_from_device(current_ring_list[0], current_ring)
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
                                if email_notification == 'enable':
                                    email.send(current_ring_name, current_ring_list, devices_ping, new_ping_status,
                                               successor_name, successor_intf, successor_to,
                                               admin_down['device'], admin_down['interface'][0],
                                               admin_down['next_device'][0])
                                    print("Отправлено письмо!")
                                sys.exit()

                            # Если на втором проходе у нас при развороте кольца, снова все узлы доступны, то
                            # это обрыв кабеля, в таком случае оставляем кольцо в развернутом виде
                            if this_is_the_second_loop:
                                print(f"Проблема вероятнее всего находится между {successor_name} и {successor_to}")
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
                                if email_notification == 'enable':
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
                                    print("Отправлено письмо!")
                                sys.exit()

                            # Если после разворота все узлы сети доступны, то это может быть обрыв кабеля, либо
                            #   временное отключение электроэнергии. Разворачиваем кольцо в исходное состояние,
                            #   чтобы определить какой именно у нас случай
                            print("Возможен обрыв кабеля, либо временное отключение электроэнергии. \n"
                                  "Разворачиваем кольцо в исходное состояние, "
                                  "чтобы определить какой именно у нас случай")
                            try_to_set_port2 = 2
                            # ------------------Закрываем порт на admin_down_device
                            while try_to_set_port2 > 0:
                                print(f'Закрываем порт {admin_down["interface"][0]} на {admin_down["device"]}')
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
                                    print(f'Поднимаем порт {successor_intf} на {successor_name}')
                                    operation_port_up2 = set_port_status(current_ring=current_ring,
                                                                         device=successor_name,
                                                                         interface=successor_intf,
                                                                         status="up")

                                    #----------------------Порт открыт
                                    if operation_port_up2 == 'DONE':
                                        wait_step = 2
                                        all_avaliable = 0
                                        while wait_step > 0:
                                            # Ждем 50 секунд
                                            print('Ожидаем 50 сек, не прерывать\n'
                                                  '0                       25                       50с')
                                            time_sleep(50)
                                            # Пингуем заново все устройства в кольце с агрегации
                                            new_ping_status = ping_from_device(current_ring_list[0], current_ring)
                                            for _, available in new_ping_status:
                                                if not available:
                                                    break  # Если есть недоступное устройство
                                            else:
                                                print("Все устройства в кольце после разворота доступны!\n")
                                                all_avaliable = 1  # Если после разворота все устройства доступны
                                            # Если по истечении 50с остались недоступные устройства, то ждем еще 50с
                                            if all_avaliable or wait_step == 1:
                                                break
                                            wait_step -= 1

                                        if all_avaliable:
                                            # Если все узлы доступны, то исключаем обрыв кабеля и оставляем кольцо в
                                            #   исходном состоянии. Разворот не требуется!
                                            delete_ring_from_deploying_list(current_ring_name)
                                            print(f"Все узлы в кольце доступны, разворот не потребовался!\n"
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
                                #----------------------Порт не открыт
                                print(f'Возвращаем закрытый раннее порт {admin_down["interface"][0]} на '
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

                            # Cохраняем статус разворота
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
                            if email_notification == 'enable':
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
                                print("Отправлено письмо!")
                            sys.exit()

                    else:
                        email.send_text(subject=f'Прерван разворот кольца {current_ring_name}',
                                        text=f'Возникло что-то невозможное во время работы с оборудованием '
                                             f'{successor_name}! ({current_ring[successor_name]["ip"]}) 😵')
                    delete_ring_from_deploying_list(current_ring_name)
                    # Выход

                else:
                    print("Все узлы недоступны!")
                    delete_ring_from_deploying_list(current_ring_name)
                break
    else:                                                       # Если все устройства недоступны по "ping", то...
        print("Все узлы сети из данного кольца недоступны!")        # ...конец кольца


def start(dev: str):
    get_ring_ = get_ring(dev)
    if not get_ring_:
        sys.exit()
    current_ring, current_ring_list, current_ring_name = get_ring_

    # Заголовок
    print('\n')
    print('-' * 20 + 'NEW SESSION' + '-' * 20)
    print(' ' * 12 + str(datetime.now()))
    print(' ' * ((51 - len(dev)) // 2) + dev + ' ' * ((51 - len(dev)) // 2))
    print('-' * 51)

    with open(f'{root_dir}/rotated_rings.yaml', 'r') as rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
        if rotated_rings:
            for rring in rotated_rings:
                if current_ring_name == rring:
                    print(f"Кольцо, к которому принадлежит узел сети {dev} уже находится в списке как развернутое\n"
                          f"(смотреть файл \"{root_dir}/rotated_rings.yaml\")")
                    return False

    devices_ping = ping_devices(current_ring)

    for _, available in devices_ping:
        if not available:
            break
    else:
        print("Все устройства в кольце доступны, разворот не требуется!")
        return False

    for _, available in devices_ping:
        if available:
            break
    else:
        print("Все устройства в кольце недоступны, разворот невозможен!")
        return False

    main(devices_ping, current_ring, current_ring_list, current_ring_name)


def time_sleep(sec: int) -> None:
    '''
    Пауза с выводом точки в одну строку, равную количеству секунд ожидания \n
    :param sec: время в секундах
    :return: None
    '''
    for s in range(sec):
        print('|', end='', flush=True)
        time.sleep(1)
    print('\n')


def interfaces(current_ring: dict, checking_device_name: str, enable_print: bool = True):
    '''
    Подключаемся к оборудованию по telnet и считываем интерфейсы, их статусы и описание
    Автоматически определяется тип производителя \n
    :param current_ring:            Кольцо
    :param checking_device_name:    Имя оборудования
    :param enable_print:            По умолчанию вывод в консоль включен
    :return:                        Список: интерфейс, статус, описание; False в случае ошибки
    '''
    with pexpect.spawn(f"telnet {current_ring[checking_device_name]['ip']}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                if enable_print:
                    print("    \033[31mTelnet недоступен!\033[0m")
                return False
            telnet.sendline(current_ring[checking_device_name]["user"])
            if enable_print:
                print(f"    Login to \033[34m{checking_device_name}\033[0m {current_ring[checking_device_name]['ip']}")
            telnet.expect("[Pp]ass")
            telnet.sendline(current_ring[checking_device_name]["pass"])
            match = telnet.expect([']', '>', '#', 'Failed to send authen-req'])
            if match == 3:
                if enable_print:
                    print('    \033[31mНеверный логин или пароль!\033[0m')
                return False
            else:
                telnet.sendline('show version')
                version = ''
                while True:
                    m = telnet.expect([r']$', '-More-', r'>$', r'#'])
                    version += str(telnet.before.decode('utf-8'))
                    if m == 1:
                        telnet.sendline(' ')
                    else:
                        break
                # ZTE
                if bool(findall(r' ZTE Corporation:', version)):
                    if enable_print:
                        print("    ZTE")

                # Huawei
                elif bool(findall(r'Unrecognized command', version)):
                    if enable_print:
                        print("    Huawei")
                    telnet.sendline("dis int des")
                    output = ''
                    num = ''
                    while True:
                        match = telnet.expect(['Too many parameters', ']', "  ---- More ----",
                                               "Unrecognized command", ">", pexpect.TIMEOUT])
                        output += str(telnet.before.decode('utf-8')).replace("[42D", '').strip()
                        # page = re.sub(" +\x08+ +\x08+", "\n", page)
                        if match == 4:
                            telnet.sendline("quit")
                            break
                        elif match == 1:
                            telnet.sendline("quit")
                            telnet.sendline("quit")
                            break
                        elif match == 2:
                            telnet.send(" ")
                            output += '\n'
                        elif match == 0 or match == 3:
                            telnet.expect('>')
                            telnet.sendline('super')
                            telnet.expect(':')
                            telnet.sendline('sevaccess')
                            telnet.expect('>')
                            telnet.sendline('dis brief int')
                            num = '2'
                            output = ''
                        else:
                            if enable_print:
                                print("    Ошибка: timeout")
                            break
                    telnet.sendline("quit")
                    output = re.sub("\n +\n", "\n", output)
                    with open(f'{root_dir}/templates/int_des_huawei{num}.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result = int_des_.ParseText(output)  # Ищем интерфейсы
                    return result

                # Cisco
                elif bool(findall(r'Cisco IOS', version)):
                    if enable_print:
                        print("    Cisco")
                    if match == 1:
                        telnet.sendline('enable')
                        telnet.expect('[Pp]ass')
                        telnet.sendline('sevaccess')
                    telnet.expect('#')
                    telnet.sendline("sh int des")
                    output = ''
                    while True:
                        match = telnet.expect([r'#$', "--More--", pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8')).replace("[42D", '').replace(
                            "        ", '')
                        # page = re.sub(" +\x08+ +\x08+", "\n", page)
                        output += page.strip()
                        if match == 0:
                            telnet.sendline("exit")
                            break
                        elif match == 1:
                            telnet.send(" ")
                            output += '\n'
                        else:
                            if enable_print:
                                print("    Ошибка: timeout")
                            break
                    output = re.sub("\n +\n", "\n", output)
                    with open(f'{root_dir}/templates/int_des_cisco.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result = int_des_.ParseText(output)  # Ищем интерфейсы
                    return result

                # D-Link
                elif bool(findall(r'Next possible completions:', version)):
                    if enable_print:
                        print("    D-Link")
                    telnet.sendline('enable admin')
                    if telnet.expect(["#", "[Pp]ass"]):
                        telnet.sendline('sevaccess')
                        telnet.expect('#')
                    telnet.sendline('disable clipaging')
                    telnet.expect('#')
                    telnet.sendline("show ports des")
                    telnet.expect('#')
                    output = telnet.before.decode('utf-8')
                    telnet.sendline('logout')
                    with open(f'{root_dir}/templates/int_des_d-link.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result = int_des_.ParseText(output)  # Ищем интерфейсы
                    return result

                # Alcatel, Linksys
                elif bool(findall(r'SW version', version)):
                    if enable_print:
                        print("    Alcatel or Linksys")
                    telnet.sendline('show interfaces configuration')
                    port_state = ''
                    while True:
                        match = telnet.expect(['More: <space>', '#', pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8'))
                        port_state += page.strip()
                        if match == 0:
                            telnet.sendline(' ')
                        elif match == 1:
                            break
                        else:
                            if enable_print:
                                print("    Ошибка: timeout")
                            break
                    with open(f'{root_dir}/templates/int_des_alcatel_linksys.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result_port_state = int_des_.ParseText(port_state)  # Ищем интерфейсы
                    telnet.sendline('show int des')
                    telnet.expect('#')
                    port_desc = ''
                    while True:
                        match = telnet.expect(['More: <space>', '#', pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8'))
                        port_desc += page.strip()
                        if match == 0:
                            telnet.sendline(' ')
                        elif match == 1:
                            telnet.sendline('exit')
                            break
                        else:
                            if enable_print:
                                print("    Ошибка: timeout")
                            break
                    with open(f'{root_dir}/templates/int_des_alcatel_linksys2.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result_port_des = int_des_.ParseText(port_desc)  # Ищем интерфейсы
                    result = []
                    for line in result_port_state:
                        for line2 in result_port_des:
                            if line[0] == line2[0]:
                                result.append([line[0], line[1], line2[1]])
                    return result

                # Edge-Core
                elif bool(findall(r'Hardware version', version)):
                    if enable_print:
                        print("    Edge-Core")

                # Zyxel
                elif bool(findall(r'ZyNOS', version)):
                    if enable_print:
                        print("    Zyxel")

                # Eltex
                elif bool(findall(r'Active-image: ', version)):
                    if enable_print:
                        print("    Eltex")
                    telnet.sendline("sh int des")
                    output = ''
                    while True:
                        match = telnet.expect([r'#$', "More: <space>", pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8')).replace("[42D", '').replace(
                            "        ", '')
                        # page = re.sub(" +\x08+ +\x08+", "\n", page)
                        output += page.strip()
                        if match == 0:
                            telnet.sendline("exit")
                            break
                        elif match == 1:
                            telnet.send(" ")
                            #output += '\n'
                        else:
                            if enable_print:
                                print("    Ошибка: timeout")
                            break
                    output = re.sub("\n +\n", "\n", output)
                    with open(f'{root_dir}/templates/int_des_eltex.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result = int_des_.ParseText(output)  # Ищем интерфейсы
                    return result

                telnet.sendline('exit')

        except pexpect.exceptions.TIMEOUT:
            if enable_print:
                print("    \033[31mВремя ожидания превышено! (timeout)\033[0m")


def search_admin_down(ring: dict, ring_list: list, checking_device_name: str, enable_print=True):
    '''
    Ищет есть ли у данного узла сети порт(ы) в состоянии "admin down" в сторону другого узла сети из этого кольца.
    Проверка осуществляется по наличию в description'е имени узла сети из текущего кольца.

    :param ring:                    Кольцо
    :param ring_list:               Список узлов сети в кольце
    :param checking_device_name:    Имя узла сети
    :param enable_print:            Вывод в консоль включен по умолчанию
    :return:    В случае успеха возвращает имя оборудования с портом(ми) "admin down" и имя оборудования к которому
                ведет этот порт и интерфейс. Если нет портов "admin down", то возвращает "False"
    '''
    if enable_print:
        print("---- def search_admin_down ----")

    result = interfaces(ring, checking_device_name, enable_print=enable_print)
    ad_to_this_host = []  # имя оборудования к которому ведет порт "admin down"
    ad_interface = []
    # print(result)
    if result:  # Если найден admin_down, то...
        for dev_name in ring_list:  # ...перебираем узлы сети в кольце:
            for res_line in result:  # Перебираем все найденные интерфейсы:
                if bool(findall(dev_name, res_line[2])) and (
                        bool(findall(r'(admin down|\*down|Down|Disabled|ADM DOWN)', res_line[1]))):
                    # ...это хост, к которому закрыт порт от проверяемого коммутатора
                    ad_to_this_host.append(dev_name)
                    ad_interface.append(res_line[0])  # интерфейс со статусом "admin down"
                    # print(checking_device_name, ad_to_this_host, ad_interface)
    if ad_to_this_host and ad_interface:
        return {"device": checking_device_name, "next_device": ad_to_this_host, "interface": ad_interface}
    else:
        return False


def interface_normal_view(interface) -> str:
    '''
    Приводит имя интерфейса к виду принятому по умолчанию для коммутаторов\n
    Например: Eth 0/1 -> Ethernet0/1
              GE1/0/12 -> GigabitEthernet1/0/12\n
    :param interface:   Интерфейс в сыром виде (raw)
    :return:            Интерфейс в общепринятом виде
    '''
    interface = str(interface)
    interface_number = findall(r"(\d+([\/\\]?\d*)*)", str(interface))
    if bool(findall('^[Ee]', interface)):
        return f"Ethernet{interface_number[0][0]}"
    elif bool(findall('^[Ff]', interface)):
        return f"FastEthernet{interface_number[0][0]}"
    elif bool(findall('^[Gg]', interface)):
        return f"GigabitEthernet{interface_number[0][0]}"
    elif bool(findall('^\d', interface)):
        return findall('^\d+', interface)[0]
    elif bool(findall('^[Tt]', interface)):
        return f'TengigabitEthernet{interface_number[0][0]}'
    else:
        return interface


def set_port_status(current_ring: dict, device: str, interface: str, status: str):
    '''
    Заходим на оборудование через telnet и устанавливаем состояние конкретного порта
    :param current_ring"    Кольцо
    :param device:          Имя узла сети, с которым необходимо взаимодействовать
    :param interface:       Интерфейс узла сети
    :param status:          "up": поднять порт, "down": положить порт
    :return:                Статус выполнения или ошибки
    '''
    print("---- def set_port_status ----")

    try_to_save = 3     # 3 попытки сохранить
    try_to_down = 3     # 3 попытки закрыть порт
    try_to_up = 3       # 3 попытки открыть порт

    with pexpect.spawn(f"telnet {current_ring[device]['ip']}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                print("    Telnet недоступен!")
                return 'telnet недоступен'
            telnet.sendline(current_ring[device]["user"])
            print(f"    Login to {device}")
            telnet.expect("[Pp]ass")
            telnet.sendline(current_ring[device]["pass"])
            print(f"    Pass to {device}")
            match = telnet.expect([']', '>', '#', 'Failed to send authen-req'])
            if match == 3:
                print('    Неверный логин или пароль!')
                return 'неверный логин или пароль'

            telnet.sendline('show version')
            version = ''
            while True:
                m = telnet.expect([r']$', '-More-', r'>$', r'#'])
                version += str(telnet.before.decode('utf-8'))
                if m == 1:
                    telnet.sendline(' ')
                else:
                    break
        except pexpect.exceptions.TIMEOUT:
            print("    Время ожидания превышено! (timeout)")
            return 'Exception: TIMEOUT'
        except pexpect.exceptions.EOF:
            print("    Exception: EOF")
            return 'Exception: EOF'

        # -----------------------------------------HUAWEI--------------------------------------------------------------
        if bool(findall(r'Unrecognized command', version)):
            try:
                if match == 1:
                    telnet.sendline("sys")
                    if telnet.expect([']', 'Unrecognized command']):
                        telnet.sendline('super')
                        print(f'    <{device}>super')
                        telnet.expect('[Pp]ass')
                        telnet.sendline('sevaccess')
                        telnet.expect('>')
                        telnet.sendline('sys')
                        telnet.expect(']')
                    print(f'    <{device}>system-view')
                interface = interface_normal_view(interface)
                telnet.sendline(f"int {interface}")
                print(f"    [{device}]interface {interface}")
                telnet.expect(f']')
                # -------------------Huawei - ADMIN DOWN-------------------
                if status == 'down':
                    # 3 попытки положить интерфейс
                    while try_to_down > 0:
                        telnet.sendline('sh')
                        print(f'    [{device}-{interface}]shutdown')
                        telnet.expect(']')
                        # проверяем статуст порта
                        telnet.sendline(f'display current-configuration interface {interface}')
                        print('    Проверяем статус порта')
                        output = ''
                        while True:
                            match = telnet.expect([']', "  ---- More ----", pexpect.TIMEOUT])
                            output += str(telnet.before.decode('utf-8')).replace("[42D", '').strip()
                            if match == 1:
                                telnet.send(" ")
                                output += '\n'
                            else:
                                break
                        print(f'\n----------------------------------'
                              f'\n{output}'
                              f'\n----------------------------------')
                        if 'interface' in output and 'shutdown' in output:
                            print(f'    Порт {interface} admin down!')
                            break
                        elif 'interface' not in output:
                            print('    Не удалось определить статус порта')
                            telnet.sendline('sh')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            print('    QUIT!')
                            return 'cant status'
                        try_to_down -= 1
                        print(f'    Порт не удалось закрыть порт, пытаемся заново (осталось {try_to_down} попыток)')
                    else:
                        print(f'    Порт не закрыт! Не удалось установить порт в состояние admin down')
                        return 'cant set down'

                # --------------------Huawei - ADMIN UP---------------------
                elif status == 'up':
                    # 3 попытки поднять интерфейс
                    while try_to_up > 0:
                        telnet.sendline('undo sh')
                        print(f'    [{device}-{interface}]undo shutdown')
                        telnet.expect(']')
                        # проверяем статуст порта
                        telnet.sendline(f'display current-configuration int {interface}')
                        print('    Проверяем статус порта')
                        output = ''
                        while True:
                            match = telnet.expect([']', "  ---- More ----", pexpect.TIMEOUT])
                            output += str(telnet.before.decode('utf-8')).replace("[42D", '').strip()
                            if match == 1:
                                telnet.send(" ")
                                output += '\n'
                            else:
                                break
                        print(f'\n----------------------------------'
                              f'\n{output}'
                              f'\n----------------------------------')
                        if 'interface' in output and 'shutdown' not in output:    # не в down
                            print(f'    Порт {interface} admin up!')
                            break
                        elif 'interface' not in output:
                            print('    Не удалось определить статус порта')
                            telnet.sendline('sh')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            print('    QUIT!')
                            return 'cant status'
                        try_to_up -= 1
                        print(f'    Порт не удалось открыть порт, пытаемся заново (осталось {try_to_up} попыток)')
                    else:
                        print(f'    Порт не открыт! Не удалось установить порт в состояние admin up')
                        return 'cant set up'
            except Exception as e:
                print(f"    Exeption: {e}")
                return 'Exception: cant set port status'
            # ----------------------Huawei - SAVE------------------------
            try:
                telnet.sendline('quit')
                telnet.expect(']')
                telnet.sendline('quit')
                telnet.expect('>')
                # 3 попытки сохранить
                while try_to_save > 0:
                    telnet.sendline('save')
                    print(f'    <{device}>save')
                    telnet.expect('[Y/N]')
                    telnet.sendline('Y')
                    telnet.sendline('\n')
                    if not telnet.expect([' successfully', '>']):
                        print('    configuration saved!')
                        telnet.sendline('quit')
                        print('    QUIT\n')
                        return 'DONE'
                    else:
                        print(f'    Не удалось сохранить! пробуем заново (осталось {try_to_save} попыток')
                    try_to_save -= 1

                telnet.sendline('quit')
                print('    QUIT\n')
                return 'DONT SAVE'
            except Exception as e:
                print(f"    Exception: Don't saved! \nError: {e}")
                return 'Exception: DONT SAVE'

        # --------------------------------------CISCO - ELTEX----------------------------------------------------------
        elif bool(findall(r'Cisco IOS', version)) or bool(findall(r'Active-image: ', version)):
            try:
                if match == 1:
                    telnet.sendline("enable")
                    print(f'    {device}>enable')
                    telnet.expect('[Pp]assword')
                    telnet.sendline('sevaccess')
                    telnet.expect('#$')
                telnet.sendline('conf t')
                telnet.expect('#$')
                interface = interface_normal_view(interface)
                telnet.sendline(f"int {interface}")
                print(f"    {device}(config)#interface {interface}")
                telnet.expect('#$')
                # -------------------Cisco, Eltex - ADMIN DOWN--------------------------
                if status == 'down':
                    # 3 попытки положить интерфейс
                    while try_to_down > 0:
                        telnet.sendline('shutdown')   # закрываем порт
                        print(f'    {device}(config-if)#shutdown')
                        telnet.expect('#$')
                        # проверяем статуст порта
                        telnet.sendline(f'do show running-config int {interface}')
                        print('    Проверяем статус порта')
                        if try_to_down == 3 and bool(findall(r'Cisco IOS', version)):
                            telnet.expect('#$')
                        output = ''
                        while True:
                            match = telnet.expect(['#$', "--More--|More: <space>", pexpect.TIMEOUT])
                            output += str(telnet.before.decode('utf-8')).strip()
                            if match == 1:
                                telnet.send(" ")
                                output += '\n'
                            else:
                                break
                        print(f'\n----------------------------------'
                              f'\n{output}'
                              f'\n----------------------------------')
                        if 'interface' in output and 'shutdown' in output:
                            print(f'    Порт {interface} admin down!')
                            break
                        elif 'interface' not in output:
                            print('    Не удалось определить статус порта')
                            telnet.sendline('no shutdown')
                            print(f'    {device}(config-if)#no shutdown')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            print('    EXIT')
                            return 'cant status'
                        try_to_down -= 1
                        print(f'    Порт не удалось закрыть порт, пытаемся заново (осталось {try_to_down} попыток)')
                    else:
                        print(f'    Порт не закрыт! Не удалось установить порт в состояние admin down')
                        telnet.sendline('exit')
                        telnet.expect('#$')
                        telnet.sendline('exit')
                        telnet.expect('#$')
                        telnet.sendline('exit')
                        print('    EXIT')
                        return 'cant set down'

                # ---------------------Cisco, Eltex - ADMIN UP----------------------------
                elif status == 'up':
                    # 3 попытки поднять интерфейс
                    while try_to_up > 0:
                        telnet.sendline('no shutdown')    # открываем порт
                        print(f'    {device}(config-if)#no shutdown')
                        telnet.expect('#$')
                        # проверяем статуст порта
                        telnet.sendline(f'do show running-config int {interface}')
                        print('    Проверяем статус порта')
                        if try_to_up == 3 and bool(findall(r'Cisco IOS', version)):
                            telnet.expect('#$')
                        output = ''
                        while True:
                            match = telnet.expect(['#$', "--More--|More: <space>", pexpect.TIMEOUT])
                            output += str(telnet.before.decode('utf-8')).strip()
                            if match == 1:
                                telnet.send(" ")
                                output += '\n'
                            else:
                                break
                        print(f'\n----------------------------------'
                              f'\n{output}'
                              f'\n----------------------------------')
                        if 'interface' in output and 'shutdown' not in output:
                            print(f'    Порт {interface} admin up!')
                            break
                        elif 'interface' not in output:
                            print('    Не удалось определить статус порта\n')
                            telnet.sendline('shutdown')
                            print(f'    {device}(config-if)#shutdown')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            print('    EXIT')
                            return 'cant status'
                        try_to_up -= 1
                        print(f'    Порт не удалось открыть порт, пытаемся заново (осталось {try_to_up} попыток)')
                    else:
                        print(f'    Порт не закрыт! Не удалось установить порт в состояние admin down')
                        telnet.sendline('exit')
                        telnet.expect('#$')
                        telnet.sendline('exit')
                        telnet.expect('#$')
                        telnet.sendline('exit')
                        print('    EXIT')
                        return 'cant set down'
            except Exception as e:
                print(f"    Exeption: {e}")
                return 'Exception: cant set port status'
            # ---------------------------Cisco, Eltex - SAVE------------------------------
            try:
                # telnet.expect('#')
                telnet.sendline('exit')
                print(f"    {device}(config-if)#exit")
                telnet.expect('#$')
                telnet.sendline('exit')
                print(f"    {device}(config)#exit")
                telnet.expect('#$')
                # 3 попытки сохранить
                # Если Cisco
                if bool(findall(r'Cisco IOS', version)):
                    while try_to_save > 0:
                        telnet.sendline('write')
                        print(f"    {device}#write")
                        telnet.expect('Building')
                        if telnet.expect(['OK', '#$']) == 0:
                            print("    Saved!")
                            telnet.sendline('exit')
                            print('    QUIT\n')
                            return 'DONE'
                        else:
                            try_to_save -= 1
                            print(f'    Не удалось сохранить! пробуем заново (осталось {try_to_save} попыток)')
                    telnet.sendline('exit')
                    print('    QUIT\n')
                    return 'DONT SAVE'
                # Если Eltex
                if bool(findall(r'Active-image: ', version)):
                    while try_to_save > 0:
                        telnet.sendline('write')
                        print(f"    {device}#write")
                        telnet.expect('Overwrite file')
                        telnet.sendline('Y')
                        telnet.expect('Y')
                        if telnet.expect(['succeeded', '#$']) == 0:
                            print("    Saved!")
                            telnet.sendline('exit')
                            print('    QUIT\n')
                            return 'DONE'
                        else:
                            try_to_save -= 1
                            print(f'    Не удалось сохранить! пробуем заново (осталось {try_to_save} попыток)')
                    telnet.sendline('exit')
                    print('    QUIT\n')
                    return 'DONT SAVE'
            except Exception as e:
                print(f"    Exception: Don't saved! \nError: {e}")
                return 'Exception: DONT SAVE'

        # ------------------------------------------D-LINK-------------------------------------------------------------
        elif bool(findall(r'Next possible completions:', version)):
            try:
                telnet.sendline('enable admin')
                if not telnet.expect(["[Pp]ass", "You already have the admin"]):
                    telnet.sendline('sevaccess')
                    telnet.expect('#')
                interface = interface_normal_view(interface)
                # -------------------------D-Link - ADMIN DOWN----------------------------
                if status == 'down':
                    # 3 попытки закрыть порт
                    while try_to_down > 0:
                        telnet.sendline(f'config ports {interface} medium_type fiber state disable')
                        print(f'    {device}#config ports {interface} medium_type fiber state disable')
                        telnet.sendline(f'config ports {interface} medium_type copper state disable')
                        print(f'    {device}#config ports {interface} medium_type copper state disable')
                        telnet.expect('#')
                        telnet.sendline('disable clipaging')
                        telnet.expect('#')
                        telnet.sendline("show ports des")
                        print('    Проверяем статус порта')
                        print(f'    {device}#show ports description')
                        telnet.expect('#')
                        telnet.sendline('\n')
                        telnet.expect('#')
                        output = telnet.before.decode('utf-8')
                        with open(f'{root_dir}/templates/int_des_d-link.template', 'r') as template_file:
                            int_des_ = textfsm.TextFSM(template_file)
                            result = int_des_.ParseText(output)  # интерфейсы
                        # Если не нашли интерфейсы или не нашли у необходимого интерфейса статуса, либо его самого
                        if not result or not [x[1] for x in result if interface_normal_view(x[0]) == interface]:
                            print('    Не удалось определить статус порта')
                            # возвращаем порт в прежнее состояние
                            telnet.sendline(f'config ports {interface} medium_type fiber state enable')
                            print(f'    {device}#config ports {interface} medium_type fiber state enable')
                            telnet.sendline(f'config ports {interface} medium_type copper state enable')
                            print(f'    {device}#config ports {interface} medium_type copper state enable')
                            telnet.expect('#')
                            telnet.sendline('logout')
                            print('    LOGOUT!')
                            return 'cant status'
                        # Проходимся по всем интерфейсам
                        for line in result:
                            # Если нашли требуемый порт и он Disabled (admin down)
                            if interface_normal_view(line[0]) == interface and line[1] == 'Disabled':
                                print(f'    Порт {interface} admin down!')
                                break
                        # Если требуемый порт НЕ Enabled
                        else:
                            try_to_down -= 1
                            print(f'    Порт не удалось закрыть, пытаемся заново (осталось {try_to_down} попыток)')
                            continue

                        break  # Если нашли требуемый порт и он Enabled
                    else:
                        print(f'    Порт не закрыт! Не удалось установить порт в состояние admin down')
                        telnet.sendline('logout')
                        print('    LOGOUT!')
                        return 'cant set down'
                # -------------------------D-Link - ADMIN UP------------------------------
                elif status == 'up':
                    # 3 попытки открыть порт
                    while try_to_up > 0:
                        telnet.sendline(f'config ports {interface} medium_type fiber state enable')
                        print(f'    {device}#config ports {interface} medium_type fiber state enable')
                        telnet.sendline(f'config ports {interface} medium_type copper state enable')
                        print(f'    {device}#config ports {interface} medium_type copper state enable')
                        telnet.expect('#')
                        telnet.sendline('disable clipaging')
                        telnet.expect('#')
                        print('    Проверяем статус порта')
                        telnet.sendline("show ports des")
                        print(f'    {device}#show ports description')
                        telnet.expect('#')
                        telnet.sendline('\n')
                        telnet.expect('#')
                        output = telnet.before.decode('utf-8')
                        with open(f'{root_dir}/templates/int_des_d-link.template', 'r') as template_file:
                            int_des_ = textfsm.TextFSM(template_file)
                            result = int_des_.ParseText(output)     # интерфейсы
                        # Если не нашли интерфейсы или не нашли у необходимого интерфейса статуса, либо его самого
                        if not result or not [x[1] for x in result if interface_normal_view(x[0]) == interface]:
                            print('    Не удалось определить статус порта')
                            # возвращаем порт в прежнее состояние
                            telnet.sendline(f'config ports {interface} medium_type fiber state disable')
                            print(f'    {device}#config ports {interface} medium_type fiber state disable')
                            telnet.sendline(f'config ports {interface} medium_type copper state disable')
                            print(f'    {device}#config ports {interface} medium_type copper state disable')
                            telnet.expect('#$')
                            telnet.sendline('logout')
                            print('    LOGOUT!')
                            return 'cant status'
                        # Проходимся по всем интерфейсам
                        for line in result:
                            # Если нашли требуемый порт и он Enabled (admin up)
                            if interface_normal_view(line[0]) == interface and line[1] == 'Enabled':
                                print(f'    Порт {interface} admin up!')
                                break
                        # Если требуемый порт НЕ Enabled
                        else:
                            try_to_up -= 1
                            print(f'    Порт не удалось открыть, пытаемся заново (осталось {try_to_up} попыток)')
                            continue

                        break   # Если нашли требуемый порт и он Enabled
                    else:
                        print(f'    Порт не закрыт! Не удалось установить порт в состояние admin up')
                        telnet.sendline('logout')
                        print('    LOGOUT!')
                        return 'cant set up'
            except Exception as e:
                print(f"    Exсeption: {e}")
                return 'Exception: cant set port status'
            # -------------------------D-Link - SAVE----------------------------------
            try:
                while try_to_save > 0:
                    telnet.sendline('save')
                    print(f'    {device}#save')
                    telnet.expect('Command: save')
                    m = telnet.expect(['[Ss]uccess|Done', '#'])
                    if m == 0:
                        print("    Saved!")
                        telnet.sendline('logout')
                        print('    LOGOUT!\n')
                        return 'DONE'
                    else:
                        try_to_save -= 1
                        print(f'    Не удалось сохранить! пробуем заново (осталось {try_to_save} попыток)')
                else:
                    print("    Don't saved!")
                    telnet.sendline('logout')
                    print('    LOGOUT!\n')
                    return 'DONT SAVE'
            except Exception as e:
                print(f"    Don't saved! \nError: {e}")
                return 'Exception: DONT SAVE'

        # -------------------------------------Alcatel - Linksys-------------------------------------------------------
        elif bool(findall(r'SW version', version)):
            try:
                telnet.sendline('conf')
                print(f'    {device}# configure')
                telnet.expect('# ')
                telnet.sendline(f'interface ethernet {interface}')
                print(f'    {device}(config)# interface ethernet {interface}')
                telnet.expect('# ')
                # ------------------Alcatel, Linksys - ADMIN DOWN---------------------
                if status == 'down':
                    while try_to_down > 0:
                        telnet.sendline('sh')
                        print(f'    {device}(config-if)# shutdown')
                        telnet.expect('# ')
                        telnet.sendline('do show interfaces configuration')
                        print('    Проверяем статус порта')
                        telnet.expect('Port')
                        port_state = ''
                        while True:
                            match = telnet.expect(['More: <space>', '# ', pexpect.TIMEOUT])
                            port_state += str(telnet.before.decode('utf-8')).strip()
                            if match == 0:
                                telnet.sendline(' ')
                            else:
                                break
                        with open(f'{root_dir}/templates/int_des_alcatel_linksys.template', 'r') as template_file:
                            int_des_ = textfsm.TextFSM(template_file)
                            result = int_des_.ParseText(port_state)  # Ищем интерфейсы
                        # Если не нашли интерфейсы или не нашли у необходимого интерфейса статуса, либо его самого
                        if not result or not [x[1] for x in result if x[0] == interface]:
                            print('    Не удалось определить статус порта')
                            # возвращаем порт в прежнее состояние
                            print('    Возвращаем порт в прежнее состояние')
                            telnet.sendline('no sh')
                            print(f'    {device}(config-if)# no shutdown')
                            telnet.sendline('exit')
                            telnet.sendline('exit')
                            telnet.sendline('exit')
                            print('    EXIT!')
                            return 'cant status'
                        # Проходимся по всем интерфейсам
                        for line in result:
                            # Если нашли требуемый порт и он admin down
                            if line[0] == interface and line[1] == 'Down':
                                print(f'    Порт {interface} admin down!')
                                break
                        # Если требуемый порт НЕ admin down
                        else:
                            try_to_down -= 1
                            print(f'    Порт не удалось закрыть, пытаемся заново (осталось {try_to_down} попыток)')
                            continue

                        break  # Если нашли требуемый порт и он admin down
                    else:
                        print(f'    Порт не закрыт! Не удалось установить порт в состояние admin down')
                        telnet.sendline('exit')
                        telnet.sendline('exit')
                        telnet.sendline('exit')
                        print('    EXIT!')
                        return 'cant set down'
                # ------------------Alcatel, Linksys - ADMIN UP-----------------------
                elif status == 'up':
                    while try_to_up > 0:
                        telnet.sendline('no sh')
                        print(f'    {device}(config-if)# no shutdown')
                        telnet.expect('# ')
                        telnet.sendline('do show interfaces configuration')
                        print('    Проверяем статус порта')
                        telnet.expect('Port')
                        port_state = ''
                        while True:
                            match = telnet.expect(['More: <space>', '# ', pexpect.TIMEOUT])
                            port_state += str(telnet.before.decode('utf-8')).strip()
                            if match == 0:
                                telnet.sendline(' ')
                            else:
                                break
                        with open(f'{root_dir}/templates/int_des_alcatel_linksys.template', 'r') as template_file:
                            int_des_ = textfsm.TextFSM(template_file)
                            result = int_des_.ParseText(port_state)  # Ищем интерфейсы
                        # Если не нашли интерфейсы или не нашли у необходимого интерфейса статуса, либо его самого
                        if not result or not [x[1] for x in result if x[0] == interface]:
                            print('    Не удалось определить статус порта')
                            # возвращаем порт в прежнее состояние
                            print('    Возвращаем порт в прежнее состояние')
                            telnet.sendline('sh')
                            print(f'    {device}(config-if)# shutdown')
                            telnet.sendline('exit')
                            telnet.sendline('exit')
                            telnet.sendline('exit')
                            print('    EXIT!')
                            return 'cant status'
                        # Проходимся по всем интерфейсам
                        for line in result:
                            # Если нашли требуемый порт и он admin up
                            if line[0] == interface and line[1] == 'Up':
                                print(f'    Порт {interface} admin up!')
                                break
                        # Если требуемый порт НЕ admin up
                        else:
                            try_to_up -= 1
                            print(f'    Порт не удалось открыть, пытаемся заново (осталось {try_to_up} попыток)')
                            continue

                        break  # Если нашли требуемый порт и он admin down
                    else:
                        print(f'    Порт не открыт! Не удалось установить порт в состояние admin up')
                        telnet.sendline('exit')
                        telnet.sendline('exit')
                        telnet.sendline('exit')
                        print('    EXIT!')
                        return 'cant set up'
            except Exception as e:
                print(f"    Exeption: {e}")
                return 'Exception: cant set port status'
            # ------------------------Alcatel, Linksys - SAVE-------------------------
            try:
                telnet.sendline('exit')
                telnet.expect('# ')
                telnet.sendline('exit')
                telnet.expect('# ')
                telnet.sendline('write')
                print(f'    {device}# write')
                telnet.expect('write')
                m = telnet.expect(['Unrecognized command', 'succeeded', '# '])
                if m == 0:
                    telnet.sendline('copy running-config startup-config')
                    print(f'    {device}# copy running-config startup-config')
                    telnet.expect('Overwrite file')
                    telnet.sendline('Yes')
                    m = telnet.expect(['!@#', 'succeeded', '# '])
                if m == 1:
                    print("    Saved!")
                    telnet.sendline('exit')
                    print('    EXIT!\n')
                    return 'DONE'
                else:
                    print('    Dont saved!')
                    telnet.sendline('exit')
                    print('    EXIT!\n')
                    return 'DONT SAVE'
            except Exception as e:
                print(f"    Don't saved! \nError: {e}")
                return 'Exception: DONT SAVE'

        # Edge-Core
        elif bool(findall(r'Hardware version', version)):
            print("    Edge-Core")

        # Zyxel
        elif bool(findall(r'ZyNOS', version)):
            print("    Zyxel")

        # ZTE
        elif bool(findall(r' ZTE Corporation:', version)):
            print("    ZTE")

        # Если не был определен вендор, то возвращаем False
        telnet.sendline('exit')
        return False


def find_port_by_desc(ring: dict, main_name: str, target_name: str):
    '''
    Поиск интерфейса с description имеющим в себе имя другого оборудования \n
    :param ring:        Кольцо
    :param main_name:   Узел сети, где ищем
    :param target_name: Узел сети, который ищем
    :return:            Интерфейс
    '''
    print("---- def find_port_by_desc ----")
    result = interfaces(ring, main_name)
    for line in result:
        if bool(findall(target_name, line[2])):  # Ищем строку, где в description содержится "target_name"
            return line[0]    # Интерфейс


# Конфигурация


def get_config(conf: str = None):
    '''
    Переопределяет глобальные переменные считывая файл конфигурации "config.conf", если такового не существует,
    то создает с настройками по умолчанию \n
    :return: None
    '''
    global email_notification
    global rings_files
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
    email_notification = 'enable' if config.get("Settings", 'email_notification') == 'enable' else 'disable'
    rings_files = get_rings()

    if conf == 'rings_files':
        return rings_files
    elif conf == 'email_notification':
        return email_notification


def return_files(path: str) -> list:
    '''
    Возвращает все файлы в папке и подпапках \n
    :param path: Путь до папки
    :return:     Список файлов
    '''
    files = os.listdir(path)
    rings_f = []
    for file in files:
        if os.path.isfile(os.path.join(path, file)):
            rings_f.append(os.path.join(path, file))
        elif os.path.isdir(os.path.join(path, file)):
            rings_f += return_files(os.path.join(path, file))
    return rings_f


def get_rings() -> list:
    '''
    Из конфигурационного файла достаем переменную "rings_directory" и указываем все найденные файлы \n
    :return: Список файлов с кольцами
    '''
    config = configparser.ConfigParser()
    config.read(f'{root_dir}/config.conf')

    rings_directory = config.get("Settings", 'rings_directory').split(',')
    rings_files = []

    for elem in rings_directory:
        elem = elem.strip()
        elem = elem[:-2] if elem.endswith('/*') else elem
        elem = elem[:-1] if elem.endswith('/') else elem
        elem = os.path.join(root_dir, elem[1:]) if elem.startswith('~') else elem
        if bool(findall('\w\*$', elem)):
            root, head = os.path.split(elem)
            sub_files = os.listdir(root)
            for sub_elem in sub_files:
                if sub_elem.startswith(head[:-1]):
                    if os.path.isfile(os.path.join(root, sub_elem)):
                        rings_files.append(os.path.join(root, sub_elem))
                    elif os.path.isdir(os.path.join(root, sub_elem)):
                        rings_files += return_files(os.path.join(root, sub_elem))
        if os.path.isfile(elem):
            rings_files.append(elem)
        elif os.path.isdir(elem):
            rings_files += return_files(elem)
    return [i for i in set(rings_files)]


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

    get_ring_ = get_ring(device)
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

    get_ring_ = get_ring(device)
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
    get_config()

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
            print(f'Файл конфигурации: \033[32m{root_dir}/config.conf\033[0m\n')
            config = configparser.ConfigParser()
            config.read(f'{root_dir}/config.conf')
            print(f'    email_notification = \033[34m{config.get("Settings", "email_notification")}\033[0m')
            print(f'    rings_directory = \033[34m{config.get("Settings", "rings_directory")}\033[0m\n')

        if (key == '-D' or key == '--device') and validation(rings_files):
            if len(sys.argv) > i+1:
                if len(sys.argv) > i+2 and sys.argv[i+2] == '--check':
                    check_admin_down(sys.argv[i + 1])

                elif len(sys.argv) > i+2 and sys.argv[i+2] == '--show-all':
                    show_all_int(sys.argv[i + 1])

                elif len(sys.argv) > i+2 and sys.argv[i+2] == '--show-int':
                    get_ring_ = get_ring(sys.argv[i + 1])
                    if not get_ring_:
                        sys.exit()
                    ring, _, ring_name = get_ring_
                    print(f'    \033[32m{ring_name}\033[0m\n')
                    print(tabulate(interfaces(ring, sys.argv[i+1]),
                                   headers=['\nInterface', 'Admin\nStatus', '\nDescription']))

                elif len(sys.argv) > i+2 and sys.argv[i+2] == '--check-des':
                    get_ring_ = get_ring(sys.argv[i + 1])
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
                    get_ring_ = get_ring(sys.argv[i + 1])
                    if not get_ring_:
                        sys.exit()
                    ring, ring_list, ring_name = get_ring_
                    ping_devices(ring)

                else:
                    start(sys.argv[i+1])
            else:
                print_help()
