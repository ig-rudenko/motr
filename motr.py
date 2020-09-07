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

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])


def __dlink_telnet_int_des(ip: str, login: str, password: str):
    '''
    Подключается через telnet к оборудованию производителя D-link
    и выдает информацию о портах, их состояние и description
    :param ip:          IP оборудования
    :param login:       Логин пользователя telnet
    :param password:    Пароль пользователя telnet
    :return:            Строка с информацией о портах, их состояние и description
    '''
    print("---- def d-link_telnet_int_des ----")
    with pexpect.spawn(f"telnet {ip}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                print("    Telnet недоступен!")
                return False
            telnet.sendline(login)
            print(f"    Login {ip}")
            telnet.expect("[Pp]ass")
            telnet.sendline(password)
            print(f"    Pass {ip}")
            if telnet.expect(['>', '#', 'Failed to send authen-req']) == 2:
                print('    Неверный логин или пароль!')
                return False
            telnet.sendline('enable admin')
            telnet.expect("[Pp]ass")
            telnet.sendline('sevaccess')
            telnet.expect('#')
            telnet.sendline('disable clipaging')
            telnet.expect('#')
            telnet.sendline("show ports des")
            output = ''
            while True:
                match = telnet.expect(['Notes', "Refresh", pexpect.TIMEOUT])
                page = str(telnet.before.decode('utf-8')).replace("[42D", '')
                # page = re.sub(" +\x08+ +\x08+", "\n", page)
                output += page.strip()
                if match == 0:
                    print("    got int des")
                    telnet.sendline("logout")
                    break
                elif match == 1:
                    telnet.send(" ")
                    output += '\n'
                else:
                    print("    Ошибка: timeout")
                    break
            output = re.sub("\n +\n", "\n", output)
            return output
        except pexpect.exceptions.TIMEOUT:
            print("    Время ожидания превышено! (timeout)")


def __cisco_telnet_int_des(ip: str, login: str, password: str):
    '''
    Подключается через telnet к оборудованию производителя Cisco
    и выдает информацию о портах, их состояние и description
    :param ip:          IP оборудования
    :param login:       Логин пользователя telnet
    :param password:    Пароль пользователя telnet
    :return:            Строка с информацией о портах, их состояние и description
    '''
    print("---- def cisco_telnet_int_des ----")
    with pexpect.spawn(f"telnet {ip}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                print("    Telnet недоступен!")
                return False
            telnet.sendline(login)
            print(f"    Login {ip}")
            telnet.expect("[Pp]ass")
            telnet.sendline(password)
            print(f"    Pass {ip}")
            match = telnet.expect(['>', '#', 'Failed to send authen-req'])
            if match == 2:
                print('    Неверный логин или пароль!')
                return False
            elif match == 0:
                telnet.sendline('enable')
                telnet.expect('[Pp]ass')
                telnet.sendline('sevaccess')
            telnet.sendline("sh int des")
            output = ''
            while True:
                match = telnet.expect(['>', '#', "--More--", pexpect.TIMEOUT])
                page = str(telnet.before.decode('utf-8')).replace("[42D", '')
                # page = re.sub(" +\x08+ +\x08+", "\n", page)
                output += page.strip()
                if match < 2:
                    print("    got int des")
                    telnet.sendline("exit")
                    break
                elif match == 2:
                    telnet.send(" ")
                    output += '\n'
                else:
                    print("    Ошибка: timeout")
                    break
            output = re.sub("\n +\n", "\n", output)
            return output
        except pexpect.exceptions.TIMEOUT:
            print("    Время ожидания превышено! (timeout)")


def __huawei_telnet_int_des(ip: str, login: str, password: str):
    '''
    Подключается через telnet к оборудованию производителя Huawei
    и выдает информацию о портах, их состояние и description
    :param ip:          IP оборудования
    :param login:       Логин пользователя telnet
    :param password:    Пароль пользователя telnet
    :return:            Строка с информацией о портах, их состояние и description
    '''
    print("---- def huawei_telnet_int_des ----")
    with pexpect.spawn(f"telnet {ip}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                print("    Telnet недоступен!")
                return False
            telnet.sendline(login)
            print(f"    Login {ip}")
            telnet.expect("[Pp]ass")
            telnet.sendline(password)
            print(f"    Pass {ip}")
            if telnet.expect(['>', ']', 'Failed to send authen-req']) == 2:
                print('    Неверный логин или пароль!')
                return False
            telnet.sendline("dis int des")
            output = ''
            while True:
                match = telnet.expect(['>', ']', "---- More ----", pexpect.TIMEOUT])
                page = str(telnet.before.decode('utf-8')).replace("[42D", '')
                # page = re.sub(" +\x08+ +\x08+", "\n", page)
                output += page.strip()
                if match == 0:
                    print("    got int des")
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
                else:
                    print("    Ошибка: timeout")
                    break
            telnet.sendline("quit")
            output = re.sub("\n +\n", "\n", output)
            return output
        except pexpect.exceptions.TIMEOUT:
            print("    Время ожидания превышено! (timeout)")


def __search_admin_down2(current_ring: dict, current_ring_list: list, checking_device_name: str):
    '''
    Ищет есть ли у данного узла сети порт(ы) в состоянии "admin down" в сторону другого узла сети из этого кольца.
    Проверка осуществляется по наличию в description'е имени узла сети из текущего кольца.

    :param current_ring:         Кольцо
    :param current_ring_list:    Список узлов сети в кольце
    :param checking_device_name: Имя узла сети
    :return:    В случае успеха возвращает имя оборудования с портом(ми) "admin down" и имя оборудования к которому
                ведет этот порт и интерфейс. Если нет портов "admin down", то возвращает "False"
    '''
    print("---- def search_admin_down ----")
    output = ''
    if current_ring[checking_device_name]["vendor"] == 'huawei':
        output = __huawei_telnet_int_des(current_ring[checking_device_name]["ip"],
                                       current_ring[checking_device_name]["user"],
                                       current_ring[checking_device_name]["pass"])

    elif current_ring[checking_device_name]["vendor"] == 'cisco':
        output = __cisco_telnet_int_des(current_ring[checking_device_name]["ip"],
                                      current_ring[checking_device_name]["user"],
                                      current_ring[checking_device_name]["pass"])

    elif current_ring[checking_device_name]["vendor"] == 'd-link':
        output = __dlink_telnet_int_des(current_ring[checking_device_name]["ip"],
                                      current_ring[checking_device_name]["user"],
                                      current_ring[checking_device_name]["pass"])

    if not output:
        print(f"Не удалось подключиться к оборудованию {checking_device_name} по telnet!")
        return False
    # print(output)
    with open(f'{root_dir}/templates/int_des_{current_ring[checking_device_name]["vendor"]}.template', 'r') as template_file:
        int_des_ = textfsm.TextFSM(template_file)
        result = int_des_.ParseText(output)  # Ищем интерфейсы "admin down"
    ad_to_this_host = []                        # имя оборудования к которому ведет порт "admin down"
    ad_interface = []
    if result:                                  # Если найден admin_down, то...
        for dev_name in current_ring_list:              # ...перебираем узлы сети в кольце:
            for res_line in result:                     # Перебираем все найденные интерфейсы:
                if bool(findall(dev_name, res_line[2])) and (
                        bool(findall('\*down', res_line[1])) or res_line[1] == 'admin down' or res_line[1] == 'Disabled'):
                    # ...это хост, к которому закрыт порт от проверяемого коммутатора
                    ad_to_this_host.append(dev_name)
                    ad_interface.append(res_line[0])            # интерфейс со статусом "admin down"
                    # print(checking_device_name, ad_to_this_host, ad_interface)
    if ad_to_this_host and ad_interface:
        return checking_device_name, ad_to_this_host, ad_interface
    else:
        return False


def ring_rotate_type(current_ring_list: list, main_dev: str, neighbour_dev: str):
    '''
    На основе двух узлов сети определяется тип "поворота" кольца относительно его структуры описанной в файле
    "rings.yaml"
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


def get_ring(device_name: str):
    '''
    Функция для поиска кольца, к которому относится переданный узел сети \n
    :param device_name: Уникальное имя узла сети
    :return: 1 Кольцо (dict),
             2 Узлы сети в кольце (list)
             3 Имя кольца (str)
    '''
    rings_files = os.listdir(f'{root_dir}/rings')
    print(rings_files)
    for file in rings_files:
        with open(f'{root_dir}/rings/{file}', 'r') as rings_yaml:      # Чтение файла
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
    sys.exit()


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
            print(f"    {device} available: True")
        else:
            status.append((device, False))
            print(f"    {device} available: False")

    with ThreadPoolExecutor(max_workers=10) as executor:    # Многопоточность
        for device in ring:
            executor.submit(ping, ring[device]['ip'], device)   # Запускаем фунцию ping и передаем ей переменные

    return status


def __find_port_by_desc2(current_ring: dict, main_name: str, target_name: str):
    '''
    Поиск интерфейса с description имеющим в себе имя другого оборудования \n
    :param current_ring: Кольцо
    :param main_name:   Узел сети, где ищем
    :param target_name: Узел сети, который ищем
    :return:            Интерфейс
    '''
    print("---- def find_port_by_desc ----")
    output = ''
    if current_ring[main_name]["vendor"] == 'huawei':
        output = __huawei_telnet_int_des(current_ring[main_name]["ip"],
                                       current_ring[main_name]["user"],
                                       current_ring[main_name]["pass"])
        # print(main_name, target_name)
    if current_ring[main_name]["vendor"] == 'cisco':
        output = __cisco_telnet_int_des(current_ring[main_name]["ip"],
                                      current_ring[main_name]["user"],
                                      current_ring[main_name]["pass"])

    if current_ring[main_name]["vendor"] == 'd-link':
        output = __dlink_telnet_int_des(current_ring[main_name]["ip"],
                                      current_ring[main_name]["user"],
                                      current_ring[main_name]["pass"])

    with open(f'{root_dir}/templates/int_des_{current_ring[main_name]["vendor"]}.template', 'r') as template_file:
        # Ищем интерфейс по шаблону
        int_des_ = textfsm.TextFSM(template_file)
        result = int_des_.ParseText(output)
        for line in result:
            if bool(findall(target_name, line[3])):  # Ищем строку, где в description содержится "target_name"
                return line[0]    # Интерфейс


def __set_port_status2(current_ring: dict, device_name: str, interface_name: str, port_status: str):
    '''
    Заходим на оборудование через telnet и устанавливаем состояние конкретного порта
    :param current_ring"    Кольцо
    :param device_name:     Имя узла сети, с которым необходимо взаимодействовать
    :param interface_name:  Интерфейс узла сети
    :param port_status:     "up": поднять порт, "down": положить порт
    :return:                В случае успеха возвращает 1, неудачи - 0
    '''
    print("---- def set_port_status ----")
    if current_ring[device_name]["vendor"] == 'huawei':
        with pexpect.spawn(f"telnet {current_ring[device_name]['ip']}") as telnet:
            try:
                if telnet.expect(["[Uu]ser", 'Unable to connect']):
                    print("    Telnet недоступен!")
                    return False
                telnet.sendline(current_ring[device_name]["user"])
                print(f"    Вход под пользователем {current_ring[device_name]['user']}")
                telnet.expect("[Pp]ass")
                telnet.sendline(current_ring[device_name]["pass"])
                print(f"    Ввод пароля ***")
                match = telnet.expect(['>', ']', 'Failed to send authen-req'])
                if match == 2:
                    print('    Неверный логин или пароль!')
                    return False
                elif match == 0:
                    telnet.sendline("sys")
                    print(f'    <{device_name}>system-view')
                telnet.expect(']')
                interface_name = interface_normal_view(interface_name)
                telnet.sendline(f"interface {interface_name}")
                print(f"    [{device_name}]interface {interface_name}")
                telnet.expect(f'-{interface_name}]')
                if port_status == 'down':
                    telnet.sendline('sh')
                    print(f'    [{device_name}-{interface_name}]shutdown')
                elif port_status == 'up':
                    telnet.sendline('undo sh')
                    print(f'    [{device_name}-{interface_name}]undo shutdown')
                telnet.expect(f'-{interface_name}]')
                telnet.sendline('quit')
                telnet.expect(']')
                telnet.sendline('quit')
                telnet.expect('>')
                telnet.sendline('save')
                telnet.expect(']')
                telnet.sendline('Y')
                telnet.expect('>')
                print('    configuration saved!')
                telnet.sendline('quit')
                print('    QUIT\n')
                return 1
            except pexpect.exceptions.TIMEOUT:
                print("    Время ожидания превышено! (timeout)")

    if current_ring[device_name]["vendor"] == 'cisco':
        with pexpect.spawn(f"telnet {current_ring[device_name]['ip']}") as telnet:
            try:
                if telnet.expect(["[Uu]ser", 'Unable to connect']):
                    print("    Telnet недоступен!")
                    return False
                telnet.sendline(current_ring[device_name]["user"])
                print(f"    Вход под пользователем {current_ring[device_name]['user']}")
                telnet.expect("[Pp]ass")
                telnet.sendline(current_ring[device_name]["pass"])
                print(f"    Ввод пароля ***")
                match = telnet.expect(['>', '#', '[Ff]ail'])
                if match == 2:
                    print('    Неверный логин или пароль!')
                    return False
                elif match == 0:
                    telnet.sendline("enable")
                    print(f'    <{device_name}>enable')
                    telnet.expect('[Pp]assword')
                    telnet.sendline('sevaccess')
                    telnet.expect('#')
                telnet.sendline('conf t')
                telnet.expect('#')
                interface_name = interface_normal_view(interface_name)
                telnet.sendline(f"interface {interface_name}")
                telnet.expect('#')
                print(f"    {device_name}(config)#interface {interface_name}")
                if port_status == 'down':
                    telnet.sendline('sh')
                    print(f'    {device_name}(config-if)#shutdown')
                elif port_status == 'up':
                    telnet.sendline('no sh')
                    print(f'    {device_name}(config-if)#no shutdown')
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
            except pexpect.exceptions.TIMEOUT:
                print("    Время ожидания превышено! (timeout)")

    if current_ring[device_name]["vendor"] == 'd-link':
        with pexpect.spawn(f"telnet {current_ring[device_name]['ip']}") as telnet:
            try:
                if telnet.expect(["[Uu]ser", 'Unable to connect']):
                    print("    Telnet недоступен!")
                    return False
                telnet.sendline(current_ring[device_name]["user"])
                print(f"    Вход под пользователем {current_ring[device_name]['user']}")
                telnet.expect("[Pp]ass")
                telnet.sendline(current_ring[device_name]["pass"])
                print(f"    Ввод пароля ***")
                match = telnet.expect(['>', '#', 'Failed to send authen-req'])
                if match == 2:
                    print('    Неверный логин или пароль!')
                    return False
                telnet.sendline('enable admin')
                telnet.expect("[Pp]ass")
                telnet.sendline('sevaccess')
                telnet.expect('#')
                interface_name = interface_normal_view(interface_name)
                if port_status == 'down':
                    telnet.sendline(f'config ports {interface_name} medium_type fiber state disable')
                    print(f'    {device_name}config ports {interface_name} medium_type fiber state disable')
                    telnet.sendline(f'config ports {interface_name} medium_type copper state disable')
                    print(f'    {device_name}config ports {interface_name} medium_type copper state disable')
                elif port_status == 'up':
                    telnet.sendline(f'config ports {interface_name} medium_type fiber state enable')
                    print(f'    {device_name}config ports {interface_name} medium_type fiber state enable')
                    telnet.sendline(f'config ports {interface_name} medium_type copper state enable')
                    print(f'    {device_name}config ports {interface_name} medium_type copper state enable')
                telnet.expect('#')
                telnet.sendline('save')
                if telnet.expect(['Success', '#']):
                    print("    Don't saved!")
                else:
                    print("    Saved!")
                telnet.sendline('logout')
                print('    QUIT\n')
                return 1
            except pexpect.exceptions.TIMEOUT:
                print("    Время ожидания превышено! (timeout)")

    return 0


def delete_ring_from_deploying_list(ring_name):
    with open(f'{root_dir}/rotated_rings.yaml', 'r') as rotated_rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rotated_rings_yaml)  # Перевод из yaml в словарь
        del rotated_rings[ring_name]
    with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
        yaml.dump(rotated_rings, save_ring, default_flow_style=False)  # Переписываем файл


def validation() -> bool:
    valid_1 = True
    validation_text = f'Проверка файла {root_dir}/rings.yaml\n'
    try:
        with open(f'{root_dir}/rings.yaml', 'r') as rings_yaml:  # Чтение файла
            try:
                rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                if rings:
                    for ring in rings:
                        for dev in rings[ring]:
                            if len(dev.split()) > 1:
                                validation_text += f'{ring} --> Имя узла сети должно быть записано в одно слово: {dev}\n'
                                valid_1 = False
                            # try:
                            #     if not rings[ring][dev]['vendor']:
                            #         validation_text += f'{ring} --> {dev} | не указан vendor'
                            #         valid_1 = False
                            #     if len(str(rings[ring][dev]['vendor']).split()) > 1:
                            #         validation_text += f'{ring} --> {dev} | '\
                            #                             f'vendor должен быть записан в одно слово: '\
                            #                             f'{rings[ring][dev]["vendor"]}'
                            #         valid_1 = False
                            # except:
                            #     validation_text += f'{ring} --> {dev} | не указан vendor'
                            #     valid_1 = False

                            try:
                                if not rings[ring][dev]['user']:
                                    validation_text += f'{ring} --> {dev} | не указан user\n'
                                    valid_1 = False
                                if len(str(rings[ring][dev]['user']).split()) > 1:
                                    validation_text += f'{ring} --> {dev} | '\
                                                        f'user должен быть записан в одно слово: '\
                                                        f'{rings[ring][dev]["user"]}\n'
                                    valid_1 = False
                            except:
                                validation_text += f'{ring} --> {dev} | не указан user\n'
                                valid_1 = False

                            try:
                                if not rings[ring][dev]['pass']:
                                    validation_text += f'{ring} --> {dev} | не указан пароль\n'
                                    valid_1 = False
                                if len(str(rings[ring][dev]['pass']).split()) > 1:
                                    validation_text += f'{ring} --> {dev} | '\
                                                        f'пароль должен быть записан в одно слово: '\
                                                        f'{rings[ring][dev]["pass"]}\n'
                                    valid_1 = False
                            except:
                                validation_text += f'{ring} --> {dev} | не указан пароль\n'
                                valid_1 = False

                            try:
                                if not rings[ring][dev]['ip']:
                                    validation_text += f'{ring} --> {dev} | не указан IP\n'
                                    valid_1 = False
                                elif not bool(findall('\d{1,4}(\.\d{1,4}){3}', rings[ring][dev]['ip'])):
                                    validation_text += f'{ring} --> {dev} | '\
                                                        f'IP указан неверно: '\
                                                        f'{rings[ring][dev]["ip"]}\n'
                                    valid_1 = False
                            except:
                                validation_text += f'{ring} --> {dev} | не указан IP\n'
                                valid_1 = False
                else:
                    validation_text += f'Файл "{root_dir}/check.yaml" пуст!\n'
                    valid_1 = False
            except Exception as e:
                validation_text += str(e)
                validation_text += '\nОшибка в синтаксисе!\n'
                valid_1 = False
    except Exception as e:
        validation_text += str(e)
        valid_1 = False

    validation_text += f'Проверка файла {root_dir}/rotated_rings.yaml\n'
    valid_2 = True
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

    if not valid_1 and not valid_2:
        email.send_text('Разворот колец невозможен!',
                        f'Ошибка в структуре файлов: \n'
                        f'{root_dir}/rings.yaml\n'
                        f'{root_dir}/rotated_rings.yaml\n\n{validation_text}')
        return False
    elif not valid_1:
        email.send_text('Разворот колец невозможен!',
                        f'Ошибка в структуре файла: \n'
                        f'{root_dir}/rings.yaml\n\n{validation_text}')
        return False
    elif not valid_2:
        email.send_text('Разворот колец невозможен!',
                        f'Ошибка в структуре файла: \n'
                        f'{root_dir}/rotated_rings.yaml\n\n{validation_text}')
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


def start(dev: str) -> None:
    current_ring, current_ring_list, current_ring_name = get_ring(dev)

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
                    sys.exit()  # Выход

    devices_ping = ping_devices(current_ring)

    for _, available in devices_ping:
        if not available:
            break
    else:
        print("Все устройства в кольце доступны, разворот не требуется!")
        sys.exit()

    for _, available in devices_ping:
        if available:
            break
    else:
        print("Все устройства в кольце недоступны, разворот невозможен!")
        sys.exit()

    main(devices_ping, current_ring, current_ring_list, current_ring_name)


def time_sleep(sec: int) -> None:
    for s in range(sec):
        print('.', end='', flush=True)
        time.sleep(1)


def interfaces(current_ring: dict, checking_device_name: str):
    '''
    Подключаемся к оборудованию по telnet и считываем интерфейсы, их статусы и описание \n
    :param current_ring:            Кольцо
    :param checking_device_name:    Имя оборудования
    :return:                        Список: интерфейс, статус, описание
    '''
    with pexpect.spawn(f"telnet {current_ring[checking_device_name]['ip']}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                print("    Telnet недоступен!")
                return False
            telnet.sendline(current_ring[checking_device_name]["user"])
            print(f"    Login to {checking_device_name}")
            telnet.expect("[Pp]ass")
            telnet.sendline(current_ring[checking_device_name]["pass"])
            print(f"    Pass to {checking_device_name}")
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
                elif bool(findall(r'Unrecognized command', version)):
                    print("    Huawei")
                    telnet.sendline("dis int des")
                    output = ''
                    num = ''
                    while True:
                        match = telnet.expect(['Too many parameters', ']', "  ---- More ----", '>', pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8')).replace("[42D", '')
                        # page = re.sub(" +\x08+ +\x08+", "\n", page)
                        output += page.strip()
                        if match == 3:
                            print("    got int des")
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
                            num = '2'
                        else:
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
                    print("    Cisco")
                    if match == 1:
                        telnet.sendline('enable')
                        telnet.expect('[Pp]ass')
                        telnet.sendline('sevaccess')
                    telnet.expect('#')
                    telnet.sendline("sh int des")
                    output = ''
                    while True:
                        match = telnet.expect(['#', "--More--", pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8')).replace("[42D", '')
                        # page = re.sub(" +\x08+ +\x08+", "\n", page)
                        output += page.strip()
                        if match == 0:
                            print("    got int des")
                            telnet.sendline("exit")
                            break
                        elif match == 1:
                            telnet.send(" ")
                            output += '\n'
                        else:
                            print("    Ошибка: timeout")
                            break
                    output = re.sub("\n +\n", "\n", output)
                    with open(f'{root_dir}/templates/int_des_cisco.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result = int_des_.ParseText(output)  # Ищем интерфейсы
                    return result

                # D-Link
                elif bool(findall(r'Next possible completions:', version)):
                    print("    D-Link")
                    telnet.sendline('enable admin')
                    telnet.expect("[Pp]ass")
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
                            print("    got int state")
                            break
                        else:
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
                            print("    got int des")
                            telnet.sendline('exit')
                            break
                        else:
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
                    print("    Edge-Core")

                # Zyxel
                elif bool(findall(r'ZyNOS', version)):
                    print("    Zyxel")
                telnet.sendline('exit')

        except pexpect.exceptions.TIMEOUT:
            print("    Время ожидания превышено! (timeout)")


def search_admin_down(current_ring: dict, current_ring_list: list, checking_device_name: str):
    '''
    Ищет есть ли у данного узла сети порт(ы) в состоянии "admin down" в сторону другого узла сети из этого кольца.
    Проверка осуществляется по наличию в description'е имени узла сети из текущего кольца.

    :param current_ring:         Кольцо
    :param current_ring_list:    Список узлов сети в кольце
    :param checking_device_name: Имя узла сети
    :return:    В случае успеха возвращает имя оборудования с портом(ми) "admin down" и имя оборудования к которому
                ведет этот порт и интерфейс. Если нет портов "admin down", то возвращает "False"
    '''
    print("---- def search_admin_down ----")

    result = interfaces(current_ring, checking_device_name)
    ad_to_this_host = []  # имя оборудования к которому ведет порт "admin down"
    ad_interface = []
    # print(result)
    if result:  # Если найден admin_down, то...
        for dev_name in current_ring_list:  # ...перебираем узлы сети в кольце:
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


def interface_normal_view(interface):
    '''
    Приводит имя интерфейса к общепринятому виду \n
    Например: Eth 0/1 -> Ethernet0/1 \n
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
                        print(f'    <{device}>system-view')
                    telnet.expect(']')
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
                    telnet.expect('>')
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
                    pass

                # Edge-Core
                elif bool(findall(r'Hardware version', version)):
                    print("    Edge-Core")

                # Zyxel
                elif bool(findall(r'ZyNOS', version)):
                    print("    Zyxel")
                telnet.sendline('exit')

        except pexpect.exceptions.TIMEOUT:
            print("    Время ожидания превышено! (timeout)")


def find_port_by_desc(current_ring: dict, main_name: str, target_name: str):
    '''
    Поиск интерфейса с description имеющим в себе имя другого оборудования \n
    :param current_ring: Кольцо
    :param main_name:   Узел сети, где ищем
    :param target_name: Узел сети, который ищем
    :return:            Интерфейс
    '''
    print("---- def find_port_by_desc ----")
    result = interfaces(current_ring, main_name)
    for line in result:
        if bool(findall(target_name, line[2])):  # Ищем строку, где в description содержится "target_name"
            return line[0]    # Интерфейс


if __name__ == '__main__':

    if len(sys.argv) == 1:
        print("Не указано имя узла сети!")
        sys.exit()

    if validation():
        start(sys.argv[1])
