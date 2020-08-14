#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from concurrent.futures import ThreadPoolExecutor
import pexpect
import yaml
from pprint import pprint
import re
from re import findall
import textfsm
from tabulate import tabulate
import subprocess


def huawei_telnet_int_des(ip: str, login: str, password: str):
    print("---- def huawei_telnet_int_des ----")
    with pexpect.spawn(f"telnet {ip}") as telnet:
        telnet.expect("[Uu]ser")
        telnet.sendline(login)
        print(f"    login {ip}")
        telnet.expect("[Pp]ass")
        telnet.sendline(password)
        print(f"    pass {ip}")
        telnet.expect(['>', ']'])
        telnet.sendline("dis int des")
        output = ''
        while True:
            match = telnet.expect(['>', ']', "---- More ----", pexpect.TIMEOUT])
            page = str(telnet.before.decode('utf-8')).replace("[42D", '')
            # page = re.sub(" +\x08+ +\x08+", "\n", page)
            output += page.strip()
            if match < 2:
                print("    got int des")
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


def search_admin_down(checking_device_name: str):
    '''
    Ищет есть ли у данного узла сети порт(ы) в состоянии "admin down" в сторону другого узла сети из этого кольца.
    Проверка осуществляется по наличию в description'е имени узла сети из текущего кольца.

    :param checking_device_name: Имя узла сети
    :return:    В случае успеха возвращает имя оборудования с портом(ми) "admin down" и имя оборудования к которому
                ведет этот порт и интерфейс. Если нет портов "admin down", то возвращает "False"
    '''
    print("---- def search_admin_down ----")
    if current_ring[checking_device_name]["vendor"] == 'huawei':
        output = huawei_telnet_int_des(current_ring[checking_device_name]["ip"],
                                       current_ring[checking_device_name]["user"],
                                       current_ring[checking_device_name]["pass"])

    with open("templates/int_des_admin_down_huawei.template", 'r') as template_file:
        int_des_ = textfsm.TextFSM(template_file)
        result = int_des_.ParseText(output)         # Ищем интерфейсы "admin down"
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


def ring_rotate_type(main_dev: str, neighbour_dev: str):
    '''
    На основе двух узлов сети определяется тип "поворота" кольца относительно его структуры описанной в файле
    "rings.yaml"
        Positive - так как в списке \n
        Negative - обратный порядок \n
    :param main_dev:        Узел сети с "admin down"
    :param neighbour_dev:   Узел сети, к которому ведет порт со статусом "admin down" узла сети 'main_dev'
    :return: positive, negative, False
    '''
    print("---- def ring_rotate_type ----")
    main_dev_index = current_ring_list.index(main_dev)
    print(f"main_dev: {main_dev} | neighbour_dev: {neighbour_dev}")
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
    :return: 1 Кольцо (dic),
             2 Узлы сети в кольце (list)
    '''
    print("---- def find_ring_by_device ----")
    with open('rings.yaml') as rings_yaml:      # Чтение файла
        rings = yaml.safe_load(rings_yaml)      # Перевод из yaml в словарь
        for ring in rings:                      # Перебираем все кольца%
            for device in rings[ring]:              # Перебираем оборудование в кольце%
                if device == device_name:               # Если нашли переданный узел сети, то...
                    current_ring = rings[ring]              # ...рассматриваем данное кольцо
                    current_ring_list = []
                    for i in current_ring:
                        current_ring_list.append(i)
                    break
    pprint(current_ring)
    print(current_ring[dev]["ip"])
    print(current_ring_list)
    return current_ring, current_ring_list


def ring_ping_status(ring: dict):
    '''
    Функция определяет, какие из узлов сети в кольце доступны по "ping" \n
    :param ring: Кольцо как "словарь"
    :return: Двумерный список: имя узла и его статус "True" - ping успешен, "False" - нет
    '''
    status = []
    print("---- def ring_ping_status ----")
    def ping(ip, device):
        result = subprocess.run(['ping', '-c', '3', '-n', ip], stdout=subprocess.DEVNULL)
        if not result.returncode:  # Проверка на доступность: 0 - доступен, 1 и 2 - недоступен
            status.append((device, True))
            print(f"dev: {device} ping: True")
        else:
            status.append((device, False))
            print(f"dev: {device} ping: False")

    with ThreadPoolExecutor(max_workers=10) as executor:
        for device in ring:
            executor.submit(ping, ring[device]['ip'], device)

    return status


def give_me_interface_name(interface: str):
    '''
    Приводит имя интерфейса к общепринятому виду \n
    Например: Eth0/1 -> Ethernet0/1 \n
    :param interface:   Интерфейс в сыром виде (raw)
    :return:            Интерфейс в общепринятом виде
    '''
    print("---- def give_me_interface_name ----")
    interface_number = findall(r"\S(\d+([\/\\]?\d*)*)", interface)
    if bool(findall('^[Ee]', interface)):
        return f"Ethernet{interface_number[0][0]}"
    elif bool(findall('^[Ff]', interface)):
        return f"FastEthernet{interface_number[0][0]}"
    elif bool(findall('^[Gg]', interface)):
        return f"GigabitEthernet{interface_number[0][0]}"


def find_port_by_desc(main_name: str, target_name: str):
    '''
    Поиск интерфейса с description имеющим в себе имя другого оборудования \n
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
    print(main_name, target_name)
    with open("templates/int_des_huawei.template", 'r') as template_file:  # Ищем интерфейс по шаблону
        int_des_ = textfsm.TextFSM(template_file)
        result = int_des_.ParseText(output)
        for line in result:
            if bool(findall(target_name, line[3])):  # Ищем строку, где в description содержится "target_name"
                return line[0]    # Интерфейс


def set_port_status(device_name: str, interface_name: str, port_status: str):
    if current_ring[device_name]["vendor"] == 'huawei':
        with pexpect.spawn(f"telnet {current_ring[device_name]['ip']}") as telnet:
            telnet.expect("[Uu]ser")
            telnet.sendline(current_ring[device_name]["user"])
            print(f"    login {current_ring[device_name]['ip']}")
            telnet.expect("[Pp]ass")
            telnet.sendline(current_ring[device_name]["pass"])
            print(f"    pass {current_ring[device_name]['ip']}")
            plvl = telnet.expect(['>', ']'])
            if plvl == 0:
                telnet.sendline("sys")
                print('sys')
            telnet.sendline(f"interface {interface_name}")
            print(f"interface {interface_name}")
            telnet.expect(f'-{interface_name}]')
            telnet.sendline(port_status)
            print(port_status)
            telnet.expect(f'-{interface_name}]')
            telnet.sendline('quit')
            telnet.expect(']')
            telnet.sendline('quit')
            telnet.expect('>')
            telnet.sendline('quit')
            print('quit')
            return 1


if __name__ == '__main__':

    successor_name = ''
    dev = 'SVSL-01-MotR-ASW1'

    current_ring, current_ring_list = find_ring_by_device(dev)

    devices_ping = ring_ping_status(current_ring)
    print(f"devices_ping: {devices_ping}")
    for device_name, device_status in devices_ping:     # Листаем узлы сети и их доступность по "ping"

        print('-'*60+'\n'+'-'*60)

        print(f"device_name: {device_name} | device_status: {device_status}")
        if device_status:                                   # Если нашли доступное устройство, то...
            admin_down = search_admin_down(device_name)         # ...ищем admin down
            print(f"admin_down: {admin_down}")
            if admin_down:                                  # [0] - host name, [1] - side host name, [2] - interface
                print(admin_down[0], admin_down[1], admin_down[2])
                occurrence = admin_down[0]                      # ...устанавливаем вхождение
                print("    Find admin down!\n")
                rotate = ring_rotate_type(occurrence, str(admin_down[1])[2:-2])         # Тип разворота кольца
                print(f'ring rotate type: {rotate}')

                if rotate == 'positive':
                    index_factor = -1
                elif rotate == 'negative':
                    index_factor = 1
                else:
                    index_factor = 0
                print("________________")
                for line in devices_ping:
                    print(line)
                print("________________")
                # Начальный индекс равен индексу соседнего узла по отношению к узлу сети, где
                # установлен принудительный обрыв кольца (admin down) в обратную сторону от разворота кольца
                curr_index = current_ring_list.index(admin_down[0])+index_factor
                iteration = 1
                if index_factor:                    # Если кольцо имеет поворот то...
                    while index_factor:                 # До тех пор, пока не найдем "преемника":
                        print(f"curr_index: {curr_index} | iteration: {iteration}")

                        for line in devices_ping:           # Листаем список
                            print(f"    devices_ping: {line} | device: {current_ring_list[curr_index]}")

                            if line[0] == current_ring_list[curr_index]:
                                print(line[0], line[1])
                                if not line[1]:                     # Если оборудование недоступно, то...
                                    pass
                                else:                               # Если оборудование доступно, то...
                                    successor_index = curr_index        # ...определяем индекс "преемника"
                                    successor_name = current_ring_list[successor_index]
                                    index_factor = 0  # Это последняя итерация "while"
                                    print("find successor")
                                    break  # Прерываем список "ping status"

                        curr_index += index_factor  # ...ищем дальше
                        iteration += 1
                        if iteration == len(current_ring_list):
                            break

                if successor_name:       # После того, как нашли "преемника"...
                    print(f"Преемник: {successor_name}")

                    # Кольцо в любом случае имеет разворот, так как найден "преемник"
                    # Необходимо установить admin down в сторону "поворота" кольца
                    if rotate == 'positive':
                        i = 1
                    else:
                        i = -1
                    successor_intf_raw = find_port_by_desc(successor_name, current_ring_list[current_ring_list.index(successor_name)+i])
                    successor_intf = give_me_interface_name(successor_intf_raw)

                    admin_down_intf = give_me_interface_name(admin_down[2][0])
                    if set_port_status(successor_name, successor_intf, "sh"):   # Закрываем порт на "преемнике"
                        if set_port_status(admin_down[0], admin_down_intf, "undo sh"): # Разворачиваем кольцо в другую сторону
                            print("Кольцо развернуто!")
    else:                                                   # Если все устройства недоступны по "ping", то...
        print("END of RING!")                                     # ...конец кольца

