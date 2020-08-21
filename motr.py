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


def cisco_telnet_int_des(ip: str, login: str, password: str):
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
            telnet.sendline(login)
            print(f"    Login {ip}")
            telnet.expect("[Pp]ass")
            telnet.sendline(password)
            print(f"    Pass {ip}")
            match = telnet.expect(['>', '#', 'Failed to send authen-req'])
            if match == 2:
                print('    Неверный логин или пароль!')
            elif match == 0:
                telnet.sendline('enable')
                telnet.expect('[Pp]ass')
                telnet.sendline('sevaccess')
            telnet.sendline("sh int des")
            output = ''
            while True:
                match = telnet.expect(['>', '#', "--More--", pexpect.TIMEOUT])
                print(match)
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


def huawei_telnet_int_des(ip: str, login: str, password: str):
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


def search_admin_down(current_ring: dict, current_ring_list: list, checking_device_name: str):
    '''
    Ищет есть ли у данного узла сети порт(ы) в состоянии "admin down" в сторону другого узла сети из этого кольца.
    Проверка осуществляется по наличию в description'е имени узла сети из текущего кольца.

    :param current_ring:         Кольцо
    :param checking_device_name: Имя узла сети
    :return:    В случае успеха возвращает имя оборудования с портом(ми) "admin down" и имя оборудования к которому
                ведет этот порт и интерфейс. Если нет портов "admin down", то возвращает "False"
    '''
    print("---- def search_admin_down ----")
    output = ''
    if current_ring[checking_device_name]["vendor"] == 'huawei':
        output = huawei_telnet_int_des(current_ring[checking_device_name]["ip"],
                                       current_ring[checking_device_name]["user"],
                                       current_ring[checking_device_name]["pass"])

    elif current_ring[checking_device_name]["vendor"] == 'cisco':
        output = huawei_telnet_int_des(current_ring[checking_device_name]["ip"],
                                       current_ring[checking_device_name]["user"],
                                       current_ring[checking_device_name]["pass"])
    if not output:
        print(f"Не удалось подключиться к оборудованию {checking_device_name} по telnet!")
        return False
    with open(f'{root_dir}/templates/int_des_admin_down_{current_ring[checking_device_name]["vendor"]}.template', 'r') as template_file:
        int_des_ = textfsm.TextFSM(template_file)
        result = int_des_.ParseText(output)  # Ищем интерфейсы "admin down"
        print(result)

    ad_to_this_host = []                        # имя оборудования к которому ведет порт "admin down"
    ad_interface = []
    if result:                                  # Если найден admin_down, то...
        for dev_name in current_ring_list:              # ...перебираем узлы сети в кольце:
            for res_line in result:                     # Перебираем все найденные admin_down:

                # Если в "description" есть узел сети, который относится к данному кольцу, то...
                if bool(findall(dev_name, res_line[3])):
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


def find_ring_by_device(device_name: str):
    '''
    Функция для поиска кольца, к которому относится переданный узел сети \n
    :param device_name: Уникальное имя узла сети
    :return: 1 Кольцо (dict),
             2 Узлы сети в кольце (list)
             3 Имя кольца (str)
    '''
    with open(f'{root_dir}/rings.yaml', 'r') as rings_yaml:      # Чтение файла
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


def ring_ping_status(ring: dict):
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


def give_me_interface_name(interface: str):
    '''
    Приводит имя интерфейса к общепринятому виду \n
    Например: Eth0/1 -> Ethernet0/1 \n
    :param interface:   Интерфейс в сыром виде (raw)
    :return:            Интерфейс в общепринятом виде
    '''
    interface_number = findall(r"\S(\d+([\/\\]?\d*)*)", interface)
    if bool(findall('^[Ee]', interface)):
        return f"Ethernet{interface_number[0][0]}"
    elif bool(findall('^[Ff]', interface)):
        return f"FastEthernet{interface_number[0][0]}"
    elif bool(findall('^[Gg]', interface)):
        return f"GigabitEthernet{interface_number[0][0]}"


def find_port_by_desc(current_ring: dict, main_name: str, target_name: str):
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
        output = huawei_telnet_int_des(current_ring[main_name]["ip"],
                                       current_ring[main_name]["user"],
                                       current_ring[main_name]["pass"])
        # print(main_name, target_name)
    if current_ring[main_name]["vendor"] == 'cisco':
        output = cisco_telnet_int_des(current_ring[main_name]["ip"],
                                      current_ring[main_name]["user"],
                                      current_ring[main_name]["pass"])

    with open(f'{root_dir}/templates/int_des_{current_ring[main_name]["vendor"]}.template', 'r') as template_file:
        # Ищем интерфейс по шаблону
        int_des_ = textfsm.TextFSM(template_file)
        result = int_des_.ParseText(output)
        for line in result:
            if bool(findall(target_name, line[3])):  # Ищем строку, где в description содержится "target_name"
                return line[0]    # Интерфейс


def set_port_status(current_ring: dict, device_name: str, interface_name: str, port_status: str):
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
                interface_name = give_me_interface_name(interface_name)
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
                telnet.expect('(config)#')
                print(f'    {device_name}(config)#')
                telnet.sendline(f"interface {interface_name}")
                telnet.expect('(config-if)#')
                print(f"    [{device_name}]interface {interface_name}")
                telnet.expect(f'-{interface_name}]')
                if port_status == 'down':
                    telnet.sendline('sh')
                    print(f'    {device_name}(config-if)#shutdown')
                elif port_status == 'up':
                    telnet.sendline('no sh')
                    print(f'    {device_name}(config-if)#no shutdown')
                telnet.expect(f'(config-if)#')
                telnet.sendline('exit')
                telnet.expect('(config)')
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
    return 0


def delete_ring_from_deploying_list(ring_name):
    with open(f'{root_dir}/rotated_rings.yaml', 'r') as rotated_rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rotated_rings_yaml)  # Перевод из yaml в словарь
        del rotated_rings[ring_name]
    with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
        yaml.dump(rotated_rings, save_ring, default_flow_style=False)  # Переписываем файл


def main(devices_ping: list, current_ring: dict, current_ring_list: list, current_ring_name: str,
         this_is_the_second_loop: bool = False):
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
                            print("Кольцо развернуто!\nОжидаем 1мин (не прерывать!)")

                            time.sleep(60)      # Ожидаем 60с на перестройку кольца
                            new_ping_status = ring_ping_status(current_ring)    # Пингуем заново все устройства в кольце
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

                                        print("Ожидаем 1мин (не прерывать!)")
                                        time.sleep(60)      # Ожидаем 60с на перестройку кольца
                                        new_ping_status = ring_ping_status(current_ring)
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
                                        main(devices_ping, current_ring, current_ring_list, current_ring_name,
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


def start(dev: str):
    current_ring, current_ring_list, current_ring_name = find_ring_by_device(dev)

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

    devices_ping = ring_ping_status(current_ring)

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


if __name__ == '__main__':

    if len(sys.argv) == 1:
        print("Не указано имя узла сети!")
        sys.exit()
    dev = sys.argv[1]

    start(dev)

