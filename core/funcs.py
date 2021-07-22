import yaml
import sys
from typing import List, Tuple
from time import sleep
from core.tc import TelnetConnect
from core.device_control import compare_ping_status, ping_devices, find_port_by_desc
from re import findall


def is_all_available(ping_status: list):
    all_available = False
    for _, available in ping_status:
        if not available:
            break
    else:
        # Все устройства доступны
        all_available = True
    return all_available


def delete_ring_from_deploying_list(ring_name: str):
    with open(f'{sys.path[0]}/rotated_rings.yaml', 'r') as rotated_rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rotated_rings_yaml)  # Перевод из yaml в словарь
        del rotated_rings[ring_name]
    with open(f'{sys.path[0]}/rotated_rings.yaml', 'w') as save_ring:
        yaml.dump(rotated_rings, save_ring, default_flow_style=False)  # Переписываем файл


def ring_rotate_type(current_ring_list: list, main_dev: str, neighbour_dev: str):
    """
    На основе двух узлов сети определяется тип "поворота" кольца относительно его структуры описанной в файле
        Positive - так как в списке \n
        Negative - обратный порядок \n
    :param current_ring_list: Кольцо (список)
    :param main_dev:        Узел сети с "admin down"
    :param neighbour_dev:   Узел сети, к которому ведет порт со статусом "admin down" узла сети 'main_dev'
    :return: positive, negative, False
    """
    main_dev_index = current_ring_list.index(main_dev)
    if current_ring_list[main_dev_index-1] == neighbour_dev:    # Если admin down смотрит в обратную сторону, то...
        return "positive"                                           # ...разворот положительный
    elif current_ring_list[main_dev_index+1] == neighbour_dev:  # Если admin down смотрит в прямом направлении, то...
        return "negative"                                           # ...разворот отрицательный
    else:
        return False


def set_ring_status(device_name: str, rings_files: list, enable_ring: bool) -> bool:
    """
    Функция для поиска кольца, к которому относится переданный узел сети и устанавливает его статус: enable (yes, no)
    :param device_name: Уникальное имя узла сети
    :param rings_files: Список с файлами, содержащими кольца
    :param enable_ring: True - активировать кольцо, False - деактивировать кольцо
    :return: None
    """
    for file in rings_files:
        with open(file, 'r') as rings_yaml:      # Чтение файла
            rings = yaml.safe_load(rings_yaml)      # Перевод из yaml в словарь
        for ring in rings:                      # Перебираем все кольца
            for device in rings[ring]:              # Перебираем оборудование в кольце%
                if device == device_name:               # Если нашли переданный узел сети, то...
                    if enable_ring:              # ...рассматриваем данное кольцо
                        rings[ring]['enable'] = 'yes'
                    else:
                        rings[ring]['enable'] = 'no'
                    with open(file, 'w') as rings_yaml:
                        yaml.dump(rings, rings_yaml, default_flow_style=False)
                    return True
    return False


def get_ring(device_name: str, rings_files: list) -> tuple:
    """
    Функция для поиска кольца, к которому относится переданный узел сети \n
    :param device_name: Уникальное имя узла сети
    :param rings_files: Список с файлами, содержащими кольца
    :return: 1 Кольцо (dict),
             2 Узлы сети в кольце (list)
             3 Имя кольца (str)
    """
    for file in rings_files:
        with open(file, 'r') as rings_yaml:      # Чтение файла
            rings = yaml.safe_load(rings_yaml)      # Перевод из yaml в словарь
        for ring in rings:                      # Перебираем все кольца
            for device in rings[ring]:              # Перебираем оборудование в кольце
                if device == device_name:               # Если нашли переданный узел сети, то...
                    current_ring: dict = rings[ring]              # ...рассматриваем данное кольцо
                    current_ring_list = []
                    current_ring_name = ring
                    for i in current_ring:
                        if i != 'enable':
                            current_ring_list.append(i)
                    return current_ring, current_ring_list, str(current_ring_name)
    return ()


def sorted_view_ring(ring_list: list, devices_ping: list, host: str, interface: str, next_host: str, with_status=True):
    """
        (SVSL-05-Vakulenchuka22-SSW3)
            ✅ SVSL-053-Gluh9-ASW4 \n
            ✅ SVSL-053-Gluh9-ASW3 \n
            ❌ SVSL-053-Gluh9-ASW2 \n
            ❌ SVSL-053-Gluh9-ASW1 \n
            ❌ SVSL-053-Gluh3-ASW1 \n
            ❌ SVSL-053-Gluh5-ASW1 \n
            ❌ SVSL-053-Gluh7-ASW1 \n
            ❌ SVSL-053-Mensh82-ASW1 \n
        (SVSL-05-Vakulenchuka22-SSW3)▲(gi1/0/8)

    :param ring_list:   Список устройств в кольце
    :param devices_ping:    Состояние устройств
    :param host:    Устройство с admin down
    :param interface:  Интерфейс admin down
    :param next_host:   Имя оборудования, с к которому ведет admin down порт
    :param with_status:  Указывать состояние устройств?
    :return:
    """

    status_before = ''
    for device in ring_list:
        for dev_name, status in devices_ping:
            if device == dev_name and device != ring_list[0]:
                if with_status:
                    if status:
                        status_before += ' ' * 5 + f'✅ {device}\n'
                    else:
                        status_before += ' ' * 5 + f'❌ {device}\n'
                else:
                    status_before += ' ' * 5 + f'   {device}\n'
    double_ring_list = ring_list + ring_list
    if next_host == double_ring_list[ring_list.index(host) - 1]:
        position_ad = 'up'
    elif next_host == double_ring_list[ring_list.index(host) + 1]:
        position_ad = 'down'
    else:
        position_ad = None
    if position_ad == 'up':
        if host == ring_list[0]:
            status_before = f'\n({ring_list[0]})\n{status_before}({ring_list[0]})▲({interface})\n'
        else:
            status_before = f'\n({ring_list[0]})\n' \
                            f'{status_before.replace(host, f"{host}▲({interface})")}' \
                            f'({ring_list[0]})\n'
    elif position_ad == 'down':
        if host == ring_list[0]:
            status_before = f'\n({ring_list[0]})▼({interface})\n{status_before}({ring_list[0]})\n'
        else:
            status_before = f'\n({ring_list[0]})\n' \
                            f'{status_before.replace(host, f"{host}▼({interface})")}' \
                            f'({ring_list[0]})\n'
    return status_before


def waiting_for_reload_ring(ring: dict, last_result: List[Tuple[str, bool]]):
    ring_list = [d for d in ring]   # Список устройств в кольце
    loops = 5   # Кол-во попыток пинга  5 * 20s = 100s
    while loops:
        sleep(20)   # Ждем 20 сек
        loops -= 1
        if not compare_ping_status(
            ping1=last_result,
            ping2=ping_devices(ring=ring),
            ring_list=ring_list
        ):  # Если кол-во доступных/недоступных устройств изменилось, то ждем еще одну итерацию
            break   # выход
    return ping_devices(ring=ring)


def reset_successor(ring: dict, ring_list: list, admin_down: dict, interfaces: dict) -> dict:
    rotate_type = ring_rotate_type(
        current_ring_list=ring_list,
        main_dev=admin_down["name"],
        neighbour_dev=admin_down["to"]
    )
    print(f'Разворот кольца: {rotate_type}')
    if rotate_type == 'positive':
        index_factor = 1
    elif rotate_type == 'negative':
        index_factor = -1
    else:
        index_factor = 0
    successor = {
        'name': ring_list[0],   # Ведущий узел
        'ip': ring[ring_list[0]]["ip"],
        'interface': find_port_by_desc(interfaces[ring_list[0]], ring_list[index_factor]),
        'to': ring_list[index_factor],
        'session': None
    }
    return successor


def successor_finder(current_ring: dict, current_ring_list: list, admin_down: dict, ping_status: list, interfaces: dict):
    # Определяем разворот кольца
    rotate_type = ring_rotate_type(
        current_ring_list=current_ring_list,
        main_dev=admin_down["name"],
        neighbour_dev=admin_down["to"]
    )
    print(f'Разворот кольца: {rotate_type}')
    if rotate_type == 'positive':
        index_factor = -1
    elif rotate_type == 'negative':
        index_factor = 1
    else:
        index_factor = 0

    # Создаем список состоящий из двух списков (элементы текущего кольца),
    #   чтобы не выходить за пределы индексации
    double_current_ring_list = current_ring_list + current_ring_list
    # Начальный индекс равен индексу соседнего узла по отношению к узлу сети, где
    #   установлен принудительный обрыв кольца (admin down) в обратную сторону от разворота кольца
    curr_index = current_ring_list.index(admin_down['name']) + index_factor
    iteration = 1
    successor = {
        'name': None,
        'ip': None,
        'interface': None,
        'to': None,
        'session': None
    }
    if index_factor:  # Если кольцо имеет поворот то...
        while index_factor:  # До тех пор, пока не найдем "преемника":
            for line in ping_status:  # Листаем список
                if line[0] == double_current_ring_list[curr_index]:
                    if not line[1]:  # Если оборудование недоступно, то...
                        pass  # ...пропуск
                    else:  # Если оборудование доступно, то...
                        successor["name"] = double_current_ring_list[curr_index]  # определяем "преемника"
                        index_factor = 0  # Это последняя итерация "while"
                        break  # Прерываем список "ping status"
            curr_index += index_factor  # ...ищем дальше
            iteration += 1
            if iteration >= len(current_ring_list) + 1:
                break

    if not successor["name"]:
        return False

    print(f"Преемник: {successor['name']}")

    # Кольцо в любом случае имеет разворот, так как найден "преемник"
    # Необходимо установить admin down в сторону "поворота" кольца
    if rotate_type == 'positive':
        i = 1
    else:
        i = -1

    successor["to"] = double_current_ring_list[current_ring_list.index(successor["name"]) + i]
    successor["interface"] = find_port_by_desc(interfaces=interfaces[successor["name"]], target_name=successor["to"])
    # Если порт преемника смотрит в сторону ведущего узла, то переопределяем порт и хост за ним,
    # чтобы тот смотрел в другую сторону
    if successor["to"] == current_ring_list[0]:
        # successor["name"] = current_ring_list[0]
        successor["interface"] = find_port_by_desc(
            interfaces=interfaces[current_ring_list[0]],
            target_name=successor["name"]
        )  # Переопределяем порт так, чтобы он был закрыт со стороны ведущего узла
        successor["to"] = successor["name"]  # Теперь порт смотрит на доступ
        successor["name"] = current_ring_list[0]  # Переопределяем преемника
    successor['ip'] = current_ring[successor["name"]]["ip"]  # Задаем ip адрес

    return successor


def rotate_ring(successor: dict, admin_down: dict) -> str:
    """
    Разворачивает кольцо
    :param successor:   Узел, на котором надо закрыть порт
    :param admin_down:  Узел, на котором надо открыть порт
    :return:    Статус разворота
    """
    # -----------------------------Закрываем порт на преемнике------------------------------------------
    successor['session'] = TelnetConnect(ip=successor["ip"], device_name=successor["name"])
    successor['session'].set_authentication()
    if not successor['session'].connect():
        return f'Error: Не удалось подключиться к {successor["name"]}'
    print(f'Подключаемся к {successor["name"]} ({successor["ip"]})')
    successor['first_port_down_status'] = successor['session'].set_port_status(
        port=successor['interface'],
        status='disable'
    )
    # Сохраняем
    successor['config_saved'] = successor['session'].save_running_configuration()
    print('config_saved:', successor['config_saved'])

    if not successor['session'].isalive():
        # Если потеряна связь с оборудованием
        return f'Error: Потеряна связь с оборудованием {successor["name"]}\n' \
               f'Порт {successor["interface"]} на {successor["name"]} закрыт? {successor["first_port_down_status"]}\n' \
               f'Конфигурация была сохранена? {successor["config_saved"]}'

    if not successor['config_saved']:
        # Если не удалось сохранить конфу и сессия доступна, пытаемся сохранить еще раз
        successor['config_saved'] = successor['session'].save_running_configuration()

    if not successor['first_port_down_status']:
        # Если произошла ошибка закрытия порта
        successor['interfaces_list'] = successor['session'].get_interfaces()  # Проверяем интерфейсы
        if not successor['interfaces_list']:  # Интерфейсы не найдены
            return f"Error: Порт {successor['interface']} на {successor['name']} не удалось закрыть!\n" \
                   f"Повторный сбор интерфейсов не удался"
        for intf in successor['interfaces_list']:
            # Если у текущего интерфейса все же порт закрыт
            if intf['interface'] == successor['interface'] \
                    and findall(r'(admin down|\*down|Down|Disabled|ADM DOWN)', intf['status']):
                successor['session'].save_running_configuration()
                break  # выходим и продолжаем далее

        else:
            return f"Error: Порт {successor['interface']} на {successor['name']} не удалось закрыть!" \
                   f'Конфигурация была сохранена? {successor["config_saved"]}'

    # ---------------------Поднимаем порт на admin_down_device--------------------------------------
    admin_down['session'] = TelnetConnect(ip=admin_down["ip"], device_name=admin_down["name"])
    admin_down['session'].set_authentication()

    # Если не удалось подключиться к оборудованию
    if not admin_down['session'].connect():
        print(f'Не удалось подключиться к {admin_down["name"]} ({admin_down["ip"]})')
        # Если сессия с преемником онлайн, если нет, то пытаемся установить заново
        if successor['session'].isalive() or successor['session'].connect():
            # Поднимаем порт на преемнике, разворот прерван!
            print(f'Поднимаем порт на {successor["name"]} ({successor["ip"]})')
            successor['second_port_up_status'] = successor['session'].set_port_status(
                port=successor['interface'],
                status='enable'
            )
            successor['config_saved'] = successor['session'].save_running_configuration()
            print('config_saved:', successor['config_saved'])

            return f'Error: Были приняты попытки развернуть кольцо\n' \
                   f'В процессе выполнения был установлен статус порта ' \
                   f'{successor["interface"]} у {successor["name"]} "admin down", ' \
                   f'а затем не удалось установить связь с {admin_down["name"]}\n' \
                   f'Далее порт {successor["interface"]} на {successor["name"]} ' \
                   f'был возвращен в исходное состояние (up)'
        # Если не удалось установить связь с преемником
        else:
            return f'Error: Разворот прерван\n' \
                   f'Не удалось подключиться к оборудованию {admin_down["name"]}\n' \
                   f'Порт {successor["interface"]} на {successor["name"]} admin down\n' \
                   f'Порт {admin_down["interface"]} на {admin_down["name"]} admin down\n\n' \
                   f'Необходимо открыть порт {successor["interface"]} на {successor["name"]}'

    print(f'Подключаемся к {admin_down["name"]} ({admin_down["ip"]})')
    admin_down['first_port_up_status'] = admin_down['session'].set_port_status(
        port=admin_down['interface'],
        status='enable'
    )
    admin_down['config_saved'] = admin_down['session'].save_running_configuration()
    print('config_saved:', admin_down['config_saved'])
    if not admin_down['session'].isalive():
        if admin_down['first_port_up_status'] and admin_down['config_saved'] and not admin_down['session'].connect():
            # Если связь с оборудованием потеряна, но удалось открыть порт и сохранить конфигурацию,
            # то кольцо считаем развернутым
            return 'Done: Кольцо было развернуто!'

        # Если связь с оборудованием потеряна и порт не был поднят
        if not admin_down['first_port_up_status'] and not admin_down['config_saved']:
            # Если сессия с преемником онлайн, если нет, то пытаемся установить заново
            if successor['session'].isalive() or successor['session'].connect():
                # Поднимаем порт на преемнике, разворот прерван
                print(f'Поднимаем порт на {successor["name"]} ({successor["ip"]}), разворот прерван')
                successor['second_port_up_status'] = successor['session'].set_port_status(
                    port=successor['interface'],
                    status='enable'
                )
                successor['config_saved'] = successor['session'].save_running_configuration()

                return f'Error: Были приняты попытки развернуть кольцо\n' \
                       f'В процессе выполнения был установлен статус порта ' \
                       f'{successor["interface"]} у {successor["name"]} "admin down", ' \
                       f'а затем была потеряна связь с оборудованием ' \
                       f'{admin_down["name"]}\n' \
                       f'Далее порт {successor["interface"]} на {successor["name"]} ' \
                       f'был возвращен в исходное состояние (up)'
            else:
                return f'Error: Разворот прерван\n' \
                       f'Не удалось подключиться к оборудованию {admin_down["name"]}\n' \
                       f'Порт {successor["interface"]} на {successor["name"]} admin down\n' \
                       f'Порт {admin_down["interface"]} на {admin_down["name"]} admin down\n\n' \
                       f'Необходимо открыть порт {successor["interface"]} на {successor["name"]}'
    return 'Done: Кольцо было развернуто!'
