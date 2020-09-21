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


def ping_from_device(device_name: str, ring: dict):
    with pexpect.spawn(f"telnet {ring[device_name]['ip']}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                print("    Telnet недоступен!")
                return False
            telnet.sendline(ring[device_name]['user'])
            print(f"    Login {ring[device_name]['user']}")
            telnet.expect("[Pp]ass")
            telnet.sendline(ring[device_name]['pass'])
            print(f"    Pass *****")
            if telnet.expect(['>', ']', '#', 'Failed to send authen-req']) == 3:
                print('    Неверный логин или пароль!')
                return False
            devices_status = [(device_name, True)]
            print(device_name, True)
            for dev in ring:
                if device_name != dev:
                    try:
                        telnet.sendline(f'ping {ring[dev]["ip"]}')
                        match = telnet.expect(['timed out', 'time out', ' 0 percent', '[Rr]eply', 'min/avg'])
                        if match <= 2:
                            telnet.sendcontrol('c')
                            devices_status.append((dev, False))
                            print(dev, False)
                        elif 2 < match <= 4:
                            telnet.sendcontrol('c')
                            devices_status.append((dev, True))
                            print(dev, True)
                        telnet.expect(['>', '#'])
                    except pexpect.exceptions.TIMEOUT:
                        devices_status.append((dev, False))
                        telnet.sendcontrol('c')
                        telnet.expect(['>', '#'])
            telnet.sendline('quit')
            telnet.sendline('logout')
            return devices_status
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

                print(f"Найден узел сети {admin_down[0]} со статусом порта {admin_down[2][0]}: admin down\n"
                      f"Данный порт ведет к {admin_down[1][0]}")
                rotate = ring_rotate_type(current_ring_list, admin_down[0], admin_down[1][0])  # Тип разворота кольца
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
                curr_index = current_ring_list.index(admin_down[0])+index_factor
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

                    print(f'Закрываем порт {successor_intf} на {successor_name}')
                    if set_port_status(current_ring,
                                       successor_name, successor_intf, "down"):   # Закрываем порт на "преемнике"
                        print(f'Поднимаем порт {admin_down[2][0]} на {admin_down[0]}')
                        if set_port_status(current_ring, admin_down[0], admin_down[2][0], "up"):
                            print("Кольцо развернуто!\nОжидаем 2мин (не прерывать!)")

                            time_sleep(120)      # Ожидаем 2 мин на перестройку кольца
                            # Пингуем заново все устройства в кольце с агрегации
                            new_ping_status = ping_from_device(current_ring_list[0], current_ring)
                            for _, available in new_ping_status:
                                if not available:
                                    break
                            else:
                                print("Все устройства в кольце после разворота доступны!\n")

                                if this_is_the_second_loop:
                                    # Если на втором проходе у нас при развороте кольца, снова все узлы доступны, то
                                    # это обрыв кабеля, в таком случае оставляем кольцо в развернутом виде

                                    print(f"Проблема вероятнее всего находится между {successor_name} и {successor_to}")
                                    with open(f'{root_dir}/rotated_rings.yaml', 'r') as rings_yaml:  # Чтение файла
                                        ring_to_save = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                                    ring_to_save[current_ring_name] = {"default_host": admin_down[0],
                                                                       "default_port": admin_down[2][0],
                                                                       "default_to": admin_down[1][0],
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
                                        email.send(current_ring_name, current_ring_list, devices_ping, new_ping_status,
                                                   successor_name, successor_intf, successor_to,
                                                   admin_down[0], admin_down[2][0], admin_down[1][0], info)
                                        print("Отправлено письмо!")
                                    sys.exit()

                                # Если после разворота все узлы сети доступны, то это может быть обрыв кабеля, либо
                                #   временное отключение электроэнергии. Разворачиваем кольцо в исходное состояние,
                                #   чтобы определить какой именно у нас случай
                                print("Возможен обрыв кабеля, либо временное отключение электроэнергии. \n"
                                      "Разворачиваем кольцо в исходное состояние, "
                                      "чтобы определить какой именно у нас случай")
                                print(f'Закрываем порт {admin_down[2][0]} на {admin_down[0]}')
                                if set_port_status(current_ring, admin_down[0], admin_down[2][0], "down"):
                                    print(f'Поднимаем порт {successor_intf} на {successor_name}')
                                    if set_port_status(current_ring, successor_name, successor_intf, "up"):

                                        print("Ожидаем 2мин (не прерывать!)")
                                        time_sleep(120)      # Ожидаем 2 мин на перестройку кольца
                                        new_ping_status = ping_from_device(current_ring_list[0], current_ring)
                                        for _, available in new_ping_status:
                                            if not available:
                                                break
                                        else:
                                            # Если все узлы доступны, то исключаем обрыв кабеля и оставляем кольцо в
                                            #   исходном состоянии. Разворот не требуется!
                                            delete_ring_from_deploying_list(current_ring_name)
                                            print(f"Все узлы в кольце доступны, разворот не потребовался!\n"
                                                  f"Узел {admin_down[0]}, состояние порта {admin_down[2][0]}: "
                                                  f"admin down в сторону узла {admin_down[1][0]}")
                                            sys.exit()

                                        # Если есть недоступные узлы, то необходимо выполнить проверку кольца заново
                                        main(new_ping_status, current_ring, current_ring_list, current_ring_name,
                                             this_is_the_second_loop=True)

                                    else:
                                        # В случае, когда мы положили порт в "admin down" на одном узле сети
                                        #   и не смогли открыть на другом, то необходимо поднять его обратно
                                        if not set_port_status(current_ring, admin_down[0], admin_down[2][0], "up"):
                                            # Если порт не поднялся, то информируем об ошибке
                                            pass
                                        else:
                                            # Подняли порт и оставляем кольцо в развернутом виде
                                            pass
                                else:
                                    # В случае, когда не удалось закрыть порт, оставляем кольцо развернутым
                                    pass

                            with open(f'{root_dir}/rotated_rings.yaml', 'r') as rings_yaml:  # Чтение файла
                                ring_to_save = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                            ring_to_save[current_ring_name] = {"default_host": admin_down[0],
                                                               "default_port": admin_down[2][0],
                                                               "default_to": admin_down[1][0],
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
                                           admin_down[0], admin_down[2][0], admin_down[1][0])
                                print("Отправлено письмо!")
                        else:
                            print(f"{admin_down[0]} Не удалось поднять порт {admin_down[2][0]}")
                            # Восстанавливаем состояние порта на преемнике
                            set_port_status(current_ring, successor_name, successor_intf, "up")
                            delete_ring_from_deploying_list(current_ring_name)
                    else:
                        print(f"{successor_name} Не удалось положить порт {successor_intf}")
                        delete_ring_from_deploying_list(current_ring_name)
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
        print('.', end='', flush=True)
        time.sleep(1)


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
        return checking_device_name, ad_to_this_host, ad_interface
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
    :return:                В случае успеха возвращает 1, неудачи - 0
    '''
    print("---- def set_port_status ----")
    with pexpect.spawn(f"telnet {current_ring[device]['ip']}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                print("    Telnet недоступен!")
                return False
            telnet.sendline(current_ring[device]["user"])
            print(f"    Login to {device}")
            telnet.expect("[Pp]ass")
            telnet.sendline(current_ring[device]["pass"])
            print(f"    Pass to {device}")
            match = telnet.expect([']', '>', '#', 'Failed to send authen-req'])
            if match == 3:
                print('    Неверный логин или пароль!')
                return False
            else:
                telnet.sendline('show version')
                version = ''
                while True:
                    m = telnet.expect([']', '-More-', '>', '#'])
                    version += str(telnet.before.decode('utf-8'))
                    if m == 1:
                        telnet.sendline(' ')
                    else:
                        break

                # ZTE
                if bool(findall(r' ZTE Corporation:', version)):
                    print("    ZTE")

                # Huawei
                elif bool(findall(r'Error: Unrecognized command', version)):
                    if match == 1:
                        telnet.sendline("sys")
                        if telnet.expect([']', 'Unrecognized command']):
                            telnet.sendline('super')
                            telnet.expect(':')
                            telnet.sendline('sevaccess')
                            telnet.expect('>')
                            telnet.sendline('sys')
                            telnet.expect(']')
                        print(f'    <{device}>system-view')
                    interface = interface_normal_view(interface)
                    telnet.sendline(f"interface {interface}")
                    print(f"    [{device}]interface {interface}")
                    telnet.expect(f'-{interface}]')
                    if status == 'down':
                        telnet.sendline('sh')
                        print(f'    [{device}-{interface}]shutdown')
                    elif status == 'up':
                        telnet.sendline('undo sh')
                        print(f'    [{device}-{interface}]undo shutdown')
                    telnet.expect(f'-{interface}]')
                    telnet.sendline('quit')
                    telnet.expect(']')
                    telnet.sendline('quit')
                    telnet.expect('>')
                    telnet.sendline('save')
                    telnet.expect(']')
                    telnet.sendline('Y')
                    if telnet.expect('>', 'Please input the file name'):
                        if telnet.expect('>', 'successfully'):
                            print('    configuration saved!')
                    telnet.sendline('quit')
                    print('    QUIT\n')
                    return 1

                # Cisco
                elif bool(findall(r'Cisco IOS', version)):
                    if match == 1:
                        telnet.sendline("enable")
                        print(f'    <{device}>enable')
                        telnet.expect('[Pp]assword')
                        telnet.sendline('sevaccess')
                        telnet.expect('#')
                    telnet.sendline('conf t')
                    telnet.expect('#')
                    interface = interface_normal_view(interface)
                    telnet.sendline(f"interface {interface}")
                    telnet.expect('#')
                    print(f"    {device}(config)#interface {interface}")
                    if status == 'down':
                        telnet.sendline('sh')
                        print(f'    {device}(config-if)#shutdown')
                    elif status == 'up':
                        telnet.sendline('no sh')
                        print(f'    {device}(config-if)#no shutdown')
                    telnet.expect(f'#')
                    telnet.sendline('exit')
                    telnet.expect('#')
                    telnet.sendline('exit')
                    telnet.expect('#')
                    telnet.sendline('write')
                    if telnet.expect(['[OoKk]', '#']) == 0:
                        print("    Saved!")
                    else:
                        print("    Don't saved!")
                    telnet.sendline('exit')
                    print('    QUIT\n')
                    return 1

                # D-Link
                elif bool(findall(r'Next possible completions:', version)):
                    telnet.sendline('enable admin')
                    telnet.expect("[Pp]ass")
                    telnet.sendline('sevaccess')
                    telnet.expect('#')
                    interface = interface_normal_view(interface)
                    if status == 'down':
                        telnet.sendline(f'config ports {interface} medium_type fiber state disable')
                        print(f'    {device}config ports {interface} medium_type fiber state disable')
                        telnet.sendline(f'config ports {interface} medium_type copper state disable')
                        print(f'    {device}config ports {interface} medium_type copper state disable')
                    elif status == 'up':
                        telnet.sendline(f'config ports {interface} medium_type fiber state enable')
                        print(f'    {device}config ports {interface} medium_type fiber state enable')
                        telnet.sendline(f'config ports {interface} medium_type copper state enable')
                        print(f'    {device}config ports {interface} medium_type copper state enable')
                    telnet.expect('#')
                    telnet.sendline('save')
                    if telnet.expect(['Success', '#']):
                        print("    Don't saved!")
                    else:
                        print("    Saved!")
                    telnet.sendline('logout')
                    print('    QUIT\n')
                    return 1

                # Alcatel, Linksys
                elif bool(findall(r'SW version', version)):
                    telnet.sendline('conf t')
                    telnet.expect('#')
                    telnet.sendline(f'interface ethernet {interface}')
                    if status == 'down':
                        telnet.sendline('sh')
                        print(f'    {device}(config-if)#shutdown')
                    elif status == 'up':
                        telnet.sendline('no sh')
                        print(f'    {device}(config-if)#no shutdown')
                    telnet.expect(f'#')
                    telnet.sendline('exit')
                    telnet.expect('#')
                    telnet.sendline('exit')
                    telnet.expect('#')
                    telnet.sendline('write')
                    if telnet.expect(['succeeded', '#']) == 0:
                        print("    Saved!")
                    else:
                        print("    Don't saved!")
                    telnet.sendline('exit')
                    print('    QUIT\n')

                # Edge-Core
                elif bool(findall(r'Hardware version', version)):
                    print("    Edge-Core")

                # Zyxel
                elif bool(findall(r'ZyNOS', version)):
                    print("    Zyxel")

                # Eltex
                elif bool(findall(r'Active-image: ', version)):
                    telnet.sendline('conf t')
                    telnet.expect('#')
                    interface = interface_normal_view(interface)
                    telnet.sendline(f"interface {interface}")
                    telnet.expect('#')
                    print(f"    {device}(config)#interface {interface}")
                    if status == 'down':
                        telnet.sendline('sh')
                        print(f'    {device}(config-if)#shutdown')
                    elif status == 'up':
                        telnet.sendline('no sh')
                        print(f'    {device}(config-if)#no shutdown')
                    telnet.expect(f'#')
                    telnet.sendline('exit')
                    telnet.expect('#')
                    telnet.sendline('exit')
                    telnet.expect('#')
                    telnet.sendline('write')
                    if telnet.expect(['succeeded', '#']) == 0:
                        print("    Saved!")
                    else:
                        print("    Don't saved!")
                    telnet.sendline('exit')
                    print('    QUIT\n')
                    return 1

                telnet.sendline('exit')

        except pexpect.exceptions.TIMEOUT:
            print("    Время ожидания превышено! (timeout)")


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


def neighbors(current_ring: dict, checking_device_name: str):
    with pexpect.spawn(f"telnet {current_ring[checking_device_name]['ip']}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                print("    Telnet недоступен!")
                return False
            telnet.sendline(current_ring[checking_device_name]["user"])
            print(f"    Login to {checking_device_name} {current_ring[checking_device_name]['ip']}")
            telnet.expect("[Pp]ass")
            telnet.sendline(current_ring[checking_device_name]["pass"])
            match = telnet.expect([']', '>', '#', 'Failed to send authen-req'])
            if match == 3:
                print('    Неверный логин или пароль!')
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
                    print("    ZTE")

                # Huawei
                elif bool(findall(r'Unrecognized command', version)):
                    print("    Huawei")
                    telnet.sendline("dis ndp")
                    output = ''
                    while True:
                        match = telnet.expect(['Too many parameters', ']', "  ---- More ----", '>', pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8')).replace("[42D", '')
                        # page = re.sub(" +\x08+ +\x08+", "\n", page)
                        output += page.strip()
                        if match == 3:
                            telnet.sendline("quit")
                            break
                        elif match == 1:
                            print("    got int des")
                            telnet.sendline("quit")
                            telnet.sendline("quit")
                            break
                        elif match == 2:
                            telnet.send(" ")
                            output += '\n'
                        elif match == 0:
                            telnet.expect('>')
                            telnet.sendline('dis brief int')
                        else:
                            print("    Ошибка: timeout")
                            break
                    telnet.sendline("quit")
                    output = re.sub("\n +\n", "\n", output)
                    # print(output)
                    with open(f'{root_dir}/templates/neighbors_huawei.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result = int_des_.ParseText(output)  # Ищем интерфейсы
                    return result

                # Cisco
                elif bool(findall(r'Cisco IOS', version)):
                    print("    Cisco")
                    if match == 1:
                        telnet.sendline('enable')
                        telnet.expect('[Pp]ass')
                        telnet.sendline('sevaccess')
                    telnet.expect('#')
                    telnet.sendline("")

                # D-Link
                elif bool(findall(r'Next possible completions:', version)):
                    print("    D-Link")
                    telnet.sendline('enable admin')
                    if telnet.expect(["#", "[Pp]ass"]):
                        telnet.sendline('sevaccess')
                        telnet.expect('#')
                    telnet.sendline('disable clipaging')
                    telnet.expect('#')
                    telnet.sendline("")


                # Alcatel, Linksys
                elif bool(findall(r'SW version', version)):
                    print("    Alcatel or Linksys")
                    telnet.sendline('')

                # Edge-Core
                elif bool(findall(r'Hardware version', version)):
                    print("    Edge-Core")

                # Zyxel
                elif bool(findall(r'ZyNOS', version)):
                    print("    Zyxel")
                telnet.sendline('exit')

        except pexpect.exceptions.TIMEOUT:
            print("    Время ожидания превышено! (timeout)")


# Функции для ключевых слов


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
            print(f'\033[32mFind admin down!\033[0m Интерфейс: \033[32m{output_check[d][2][0]}\033[0m '
                  f'ведет к устройству \033[32m{output_check[d][1][0]}\033[0m')
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
            print(f'\n\033[4mRotated rings\033[0m: \033[32m{len(r_rings)}\033[0m')
            for line in r_rings:
                if line:
                    print(line)

        if key == '--conf':
            print(f'Файл конфигурации: \033[32m{root_dir}/config.conf\033[0m\n')
            config = configparser.ConfigParser()
            config.read(f'{root_dir}/config.conf')
            print(f'    email_notification = \033[34m{config.get("Settings", "email_notification")}\033[0m')
            print(f'    rings_directory = \033[34m{config.get("Settings", "rings_directory")}\033[0m\n')

        if key == '-D' or key == '--device' and validation(rings_files):
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

                else:
                    start(sys.argv[i+1])
            else:
                print_help()
