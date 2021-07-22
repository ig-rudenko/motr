import pprint
import subprocess
from re import findall
from typing import Tuple, List
from concurrent.futures import ThreadPoolExecutor   # Многопоточность

from core.tc import TelnetConnect


def get_interfaces(current_ring: dict, checking_device_name: str, interfaces: dict):
    """
    Подключаемся к оборудованию по telnet и считываем интерфейсы, их статусы и описание
    Автоматически определяется тип производителя \n
    :param current_ring:            Кольцо
    :param checking_device_name:    Имя оборудования
    :param interfaces:              Словарь для хранения
    :return:                        Список: интерфейс, статус, описание; False в случае ошибки
    """
    session = TelnetConnect(
        device_name=checking_device_name,
        ip=current_ring[checking_device_name]['ip']
    )
    session.set_authentication()
    session.connect()
    interfaces[checking_device_name] = session.get_interfaces()
    session.close()


def search_admin_down(ring_list: list, checking_device_name: str, interfaces: list):
    """
    Ищет есть ли у данного узла сети порт(ы) в состоянии "admin down" в сторону другого узла сети из этого кольца.
    Проверка осуществляется по наличию в description'е имени узла сети из текущего кольца.

    :param ring_list:               Список узлов сети в кольце
    :param checking_device_name:    Имя узла сети
    :param interfaces:              Интерфейсы узла сети
    :return:    В случае успеха возвращает имя оборудования с портом(ми) "admin down" и имя оборудования к которому
                ведет этот порт и интерфейс. Если нет портов "admin down", то возвращает "False"
    """
    ad_to_this_host = []    # имя оборудования к которому ведет порт "admin down"
    ad_interface = []

    if interfaces:  # Если найден
        for dev_name in ring_list:  # ...перебираем узлы сети в кольце:
            for res_line in interfaces:  # Перебираем все найденные интерфейсы:
                if dev_name in res_line['description'] and \
                        findall(r'(admin down|\*down|Down|Disabled|ADM DOWN)', res_line['status']):
                    # ...это хост, к которому закрыт порт от проверяемого коммутатора
                    ad_to_this_host.append(dev_name)
                    ad_interface.append(res_line['interface'])  # интерфейс со статусом "admin down"
    if ad_to_this_host and ad_interface:
        return {"device": checking_device_name, "next_device": ad_to_this_host, "interface": ad_interface}
    else:
        return []


def find_port_by_desc(interfaces: list, target_name: str) -> str:
    """
    Поиск интерфейса с description имеющим в себе имя другого оборудования

    :param interfaces:  Список интерфейсов
    :param target_name: Имя, которое необходимо найти
    :return:            Интерфейс
    """
    print("---- def find_port_by_desc ----")

    for line in interfaces:
        if target_name in line['description']:  # Ищем строку, где в description содержится "target_name"
            return line['interface']    # Интерфейс


def ping_devices(ring: dict) -> List[Tuple[str, bool]]:
    """
    Функция определяет, какие из узлов сети в кольце доступны по "ping" \n
    :param ring: Кольцо
    :return: Двумерный список: имя узла и его статус "True" - ping успешен, "False" - нет
    """
    status: List[Tuple[str, bool]] = []

    def ping(ip, device):
        result = subprocess.run(['ping', '-c', '3', '-n', ip], stdout=subprocess.DEVNULL)
        if not result.returncode:  # Проверка на доступность: 0 - доступен, 1 и 2 - недоступен
            status.append((device, True))
        else:
            status.append((device, False))

    with ThreadPoolExecutor() as executor:    # Многопоточность
        for device in ring:
            executor.submit(ping, ring[device]['ip'], device)   # Запускаем фунцию ping и передаем ей переменные
    # for device in ring_list:
    #     for dev_name, stat in status:
    #         if device == dev_name:
    #             if stat:
    #                 print(f"    ✅ {device}")
    #             else:
    #                 print(f"    ❌ {device}")
    # print('-------------------')
    return status


def compare_ping_status(ping1, ping2, ring_list):
    check1 = []
    check2 = []

    for dev in ring_list:
        for dev_ping1 in ping1:
            if dev_ping1[0] == dev:
                check1.append(dev_ping1)
        for dev_ping2 in ping2:
            if dev_ping2[0] == dev:
                check2.append(dev_ping2)
    return check1 == check2
