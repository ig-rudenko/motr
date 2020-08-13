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


def huawei_telnet_int_des(ip, login, password):
    with pexpect.spawn(f"telnet {ip}") as telnet:
        telnet.expect("[Uu]ser")
        telnet.sendline(login)
        print(f"login {ip}")
        telnet.expect("[Pp]ass")
        telnet.sendline(password)
        print(f"pass {ip}")
        telnet.expect(['>', ']'])
        telnet.sendline("dis int des")
        output = ''
        while True:
            match = telnet.expect(['>', ']', "---- More ----", pexpect.TIMEOUT])
            print(match)
            page = str(telnet.before.decode('utf-8')).replace("[42D", '')
            # page = re.sub(" +\x08+ +\x08+", "\n", page)
            output += page.strip()
            if match < 2:
                print("match 0 or 1")
                break
            elif match == 2:
                print("match 2")
                telnet.send(" ")
                output += '\n'
            else:
                print("Ошибка: timeout")
                break
        telnet.sendline("quit")
        output = re.sub("\n +\n", "\n", output)
        return output


def search_admin_down(checking_device_name):
    '''
    Ищет есть ли у данного узла сети порт(ы) в состоянии "admin down" в сторону другого узла сети из этого кольца.
    Проверка осуществляется по наличию в description'е имени узла сети из текущего кольца.

    :param checking_device_name: Имя узла сети
    :return:    В случае успеха возвращает имя оборудования с портом(ми) "admin down" и имя оборудования к которому
                ведет этот порт и интерфейс. Если нет портов "admin down", то возвращает "False"
    '''
    if current_ring[checking_device_name]["vendor"] == 'huawei':
        output = huawei_telnet_int_des(current_ring[checking_device_name]["ip"],
                                       current_ring[checking_device_name]["user"],
                                       current_ring[checking_device_name]["pass"])

    with open("templates/admin_down_huawei.template", 'r') as template_file:
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


def ring_rotate_type(main_dev, neighbour_dev):
    '''
    На основе двух узлов сети определяется тип "поворота" кольца относительно его структуры описанной в файле
    "rings.yaml"
        Positive - так как в списке\n
        Negative - обратный порядок
    :param main_dev:        Узел сети с "admin down"
    :param neighbour_dev:   Узел сети, к которому ведет порт со статусом "admin down" узла сети 'main_dev'
    :return: positive, negative, False
    '''
    main_dev_index = current_ring_list.index(main_dev)
    print(f"main_dev: {main_dev} | neighbour_dev: {neighbour_dev}")
    print(main_dev_index, current_ring_list[main_dev_index-1], current_ring_list[main_dev_index+1])
    if current_ring_list[main_dev_index-1] == neighbour_dev:
        return "positive"
    elif current_ring_list[main_dev_index+1] == neighbour_dev:
        return "negative"
    else:
        return False


def find_ring_by_device(device_name):
    '''
    Функция для поиска кольца, к которому относится переданный узел сети
    :param device_name: Уникальное имя узла сети
    :return: 1 Словарь - кольцо,
             2 Список узлов сети в кольце
    '''
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


def ring_ping_status(ring):
    '''
    Функция определяет, какие из узлов сети в кольце доступны по "ping"
    :param ring: Кольцо как "словарь"
    :return: Двумерный список: имя узла и его статус "True" - ping успешен, "False" - нет
    '''
    status, ring_list = [], []

    def ping(ip):
        result = subprocess.run(['ping', '-c', '3', '-n', ip], stdout=subprocess.DEVNULL)
        if not result.returncode:  # Проверка на доступность: 0 - доступен, 1 и 2 - недоступен
            status.append(True)
        else:
            status.append(False)

    with ThreadPoolExecutor(max_workers=10) as executor:
        for device in ring:
            executor.submit(ping, ring[device]['ip'])
            ring_list.append(device)

    return zip(ring_list, status)


def give_me_interface_name(interface):
    interface_number = findall(r"\S(\d+([\/\\]?\d*)*)", interface)
    if bool(findall('^[Ee]', interface)):
        return f"Ethernet{interface_number}"
    elif bool(findall('^[Ff]', interface)):
        return f"FastEthernet{interface_number}"
    elif bool(findall('^[Gg]', interface)):
        return f"GigabitEthernet{interface_number}"


# def successor():
#     if ring_rotate_type()

# for elem in current_ring:
#     if current_ring[elem]["vendor"] == "huawei":
#         int_des = huawei_telnet_int_des(current_ring[elem]["ip"],
#                                         current_ring[elem]["user"],
#                                         current_ring[elem]["pass"])
#         with open('output', 'a+') as file:
#             file.write(int_des)
#             print(int_des)


if __name__ == '__main__':

    dev = 'SVSL-01-MotR-ASW1'

    current_ring, current_ring_list = find_ring_by_device(dev)

    devices_ping = ring_ping_status(current_ring)

    for device_name, device_status in devices_ping:     # Листаем узлы сети и их доступность по "ping"
        if device_status:                                   # Если нашли доступное устройство, то...
            admin_down = search_admin_down(device_name)     # Ищем admin down

            if admin_down:                                  # [0] - host name, [1] - side host name, [2] - interface
                occurrence = admin_down[0]                      # ...устанавливаем вхождение
                print("find admin down!")
                rotate = ring_rotate_type(occurrence, str(admin_down[1])[2:-2])         # Тип разворота кольца
                print(f'ring rotate type: {rotate}')

                if rotate == 'positive':
                    index_factor = -1
                elif rotate == 'negative':
                    index_factor = 1
                else:
                    index_factor = 0

                start_index = current_ring_list.index(admin_down[0])    # Начальный индекс равен узлу сети с портом admin down
                print(rotate)
                if index_factor:                    # Если кольцо имеет поворот то...
                    while index_factor:                 # До тех пор, пока не найдем преемника:
                        for line in devices_ping:           # Листаем список
                            if line[0] == current_ring_list[start_index]:
                                if not line[1]:                     # Если оборудование недоступно, то...
                                    start_index += index_factor         # ...ищем дальше
                            elif line[0] == current_ring_list[start_index] and line[1]:     # Если оборудование доступно, то...
                                successor_index = start_index                                       # ...определяем индекс преемника
                                index_factor = 0
                                break
                        else:               # Если все хосты недоступны, то...
                            break               # ...прерываем цикл "while"



    else:                                                   # Если все устройства недоступны по "ping", то...
        print("RING DEAD!")                                     # ...кольцо "мертвое"

        # for line in devices_ping:
        #     print(line[1])

