from re import findall, sub
import sys
import textfsm
from core.intf_view import interface_normal_view
import pexpect


def save_running_configuration(session, privilege_mode_password):
    """
    Сохраняет текущую конфигурацию в стартовую

    :param session:     Залогиненная сессия удаленного терминала
    :param privilege_mode_password:  Пароль от привилегированного режима
    :return:            True - конфигурация сохранена, False - конфигурацию не удалось сохранить
    """
    try:
        enable_admin(session, privilege_mode_password)
        session.sendline('save')
        print('*****:5# save')
        if session.expect([r'\S+#', r'Done|\[OK\]'], timeout=60):
            print('Saving all configurations to NV-RAM...... Done.')
            return True
        print('Failed.')
        return False
    except pexpect.TIMEOUT:
        print('Timeout!')
        return False
    except pexpect.EOF:
        print('Потеряна связь с оборудованием')
        return False


def set_port_status(session, port: str, status: str, privilege_mode_password: str) -> bool:
    try:
        enable_admin(session, privilege_mode_password)
        port = findall(r'\d+', port)[0]
        if status == 'enable':
            session.sendline(f'config ports {port} medium_type fiber state enable')
            print(f'*****:5# config ports {port} medium_type fiber state enable')
            session.sendline(f'config ports {port} medium_type copper state enable')
            print(f'*****:5# config ports {port} medium_type copper state enable')
            session.expect(r'\S+#\s*$')
            return True
        if status == 'disable':
            session.sendline(f'config ports {port} medium_type fiber state disable')
            print(f'*****:5# config ports {port} medium_type fiber state disable')
            session.sendline(f'config ports {port} medium_type copper state disable')
            print(f'*****:5# config ports {port} medium_type copper state disable')
            session.expect(r'\S+#\s*$')
            return True
    except pexpect.TIMEOUT:
        print('Timeout!')
        return False
    except pexpect.EOF:
        print('Потеряна связь с оборудованием')
        return False


def send_command(session, command: str, privilege_mode_password: str, prompt: str = r'\S+#', next_catch: str = None,
                 expect: bool = True):
    if not enable_admin(session, privilege_mode_password):
        return False

    session.sendline(command)
    # print(f'send command: {command}')
    if not expect:
        return True
    session.expect(command)
    if next_catch:
        session.expect(next_catch)
    session.expect(prompt)
    return session.before.decode('utf-8')


def enable_admin(session, privilege_mode_password: str) -> bool:
    """
    Повышает уровень привилегий до уровня администратора
    :param session: TELNET Сессия
    :param privilege_mode_password: пароль от уровня администратора
    :return: True/False
    """
    status = True
    try:
        session.sendline('enable admin')
        if not session.expect(
            [
                "[Pp]ass",           # 0 - ввод пароля
                r"You already have"  # 1 - уже администратор
            ]
        ):
            session.sendline(privilege_mode_password)
        while session.expect(['#', 'Fail!']):
            session.sendline('\n')
            print('privilege_mode_password wrong!')
            status = False
        if status:
            session.sendline('disable clipaging')   # отключение режима постраничного вывода
            session.expect('#')
    except pexpect.EOF:
        return False
    except pexpect.TIMEOUT:
        return False
    return status


def show_interfaces(telnet_session, privilege_mode_password: str) -> list:
    if not enable_admin(telnet_session, privilege_mode_password):
        return []
    telnet_session.sendline("show ports des")
    telnet_session.expect('#')
    output = telnet_session.before.decode('utf-8')
    with open(f'{sys.path[0]}/templates/int_des_d-link.template', 'r') as template_file:
        int_des_ = textfsm.TextFSM(template_file)
        result = int_des_.ParseText(output)  # Ищем интерфейсы
    return result


def show_mac(telnet_session, interfaces: list, interface_filter: str) -> str:
    intf_to_check = []
    mac_output = ''
    not_uplinks = True if interface_filter == 'only-abonents' else False

    for line in interfaces:
        if (
                (not not_uplinks and bool(findall(interface_filter, line[3])))  # интерфейсы по фильтру
                or (not_uplinks and  # ИЛИ все интерфейсы, кроме:
                    'SVSL' not in line[3].upper() and  # - интерфейсов, которые содержат "SVSL"
                    'POWER_MONITORING' not in line[3].upper())  # - POWER_MONITORING
                and not ('down' in line[2].lower() and not line[3])  # - пустые интерфейсы с LinkDown
                and 'disabled' not in line[1].lower()  # И только интерфейсы со статусом admin up
        ):  # Если описание интерфейсов удовлетворяет фильтру
            intf_to_check.append([line[0], line[3]])

    if not intf_to_check:
        if not_uplinks:
            return 'Порты абонентов не были найдены либо имеют статус admin down (в этом случае MAC\'ов нет)'
        else:
            return f'Ни один из портов не прошел проверку фильтра "{interface_filter}" ' \
                   f'либо имеет статус admin down (в этом случае MAC\'ов нет)'

    for intf in intf_to_check:
        telnet_session.sendline(f'show fdb port {interface_normal_view(intf[0])}')
        telnet_session.expect('#')
        mc_output = sub(r'[\W\S]+VID', 'VID', str(telnet_session.before.decode('utf-8')))
        mc_output = sub(r'Total Entries[\s\S]+', ' ', mc_output)
        separator_str = '─' * len(f'Интерфейс: {intf[0]} ({intf[1]})')
        mac_output += f"\n    Интерфейс: {intf[0]} ({intf[1]})\n    {separator_str}\n{mc_output}"
    if not intf_to_check:
        return f'Не найдены запрашиваемые интерфейсы на данном оборудовании!'
    return mac_output


def show_device_info(telnet_session, privilege_mode_password: str):
    info = ''
    if not enable_admin(telnet_session, privilege_mode_password):
        return

    # VERSION
    telnet_session.sendline('show switch')
    telnet_session.expect('Command: show switch')
    telnet_session.expect('\S+#')
    info += telnet_session.before.decode('utf-8')
    info += ''

    # CPU
    telnet_session.sendline('show utilization cpu')
    telnet_session.expect('Command: show utilization cpu\W+')
    telnet_session.expect('\S+#')
    info += '   ┌──────────────┐\n'
    info += '   │ ЗАГРУЗКА CPU │\n'
    info += '   └──────────────┘\n'
    info += telnet_session.before.decode('utf-8')
    return info


def show_cable_diagnostic(telnet_session, privilege_mode_password: str):
    info = ''
    enable_admin(telnet_session, privilege_mode_password)

    # CABLE_DIAGNOSTIC
    telnet_session.sendline('cable_diag ports all')
    telnet_session.expect('Perform Cable Diagnostics ...\W+')
    telnet_session.expect('\S+#')
    info += '''
            ┌─────────────────────┐
            │ Диагностика кабелей │
            └─────────────────────┘
            
    Pair Open — конец линии (либо обрыв) на растоянии ХХ метров
    Link Up, длинна ХХ метров
    Link Down, OK — нельзя измерить длинну кабеля (но нагрузка есть)
    Link Down, No Cable — нет кабеля
    
    '''
    info += telnet_session.before.decode('utf-8')
    return info


def show_vlans(telnet_session, interfaces: list, privilege_mode_password: str) -> tuple:

    def range_to_numbers(ports_string: str) -> list:
        ports_split = ports_string.split(',')
        res_ports = []
        for p in ports_split:
            if '-' in p:
                port_range = list(range(int(p.split('-')[0]), int(p.split('-')[1]) + 1))
                for pr in port_range:
                    res_ports.append(int(pr))
            else:
                res_ports.append(int(p))

        return sorted(res_ports)

    enable_admin(telnet_session, privilege_mode_password)
    telnet_session.sendline('show vlan')
    telnet_session.expect('#', timeout=20)
    output = telnet_session.before.decode('utf-8')
    with open(f'{sys.path[0]}/templates/vlans_templates/d-link.template', 'r') as template_file:
        vlan_templ = textfsm.TextFSM(template_file)
        result_vlan = vlan_templ.ParseText(output)
    # сортируем и выбираем уникальные номера портов из списка интерфейсов
    port_num = set(sorted([int(findall(r'\d+', p[0])[0]) for p in interfaces]))

    # Создаем словарь, где ключи это кол-во портов, а значениями будут вланы на них
    ports_vlan = {num: [] for num in range(1, len(port_num)+1)}

    vlans_info = ''     # Информация о имеющихся vlan
    for vlan in result_vlan:
        # Если имя vlan не равно его vid
        if vlan[0] != vlan[1]:
            vlans_info += f'VLAN: {vlan[0]} ({vlan[1]})\n'
        else:
            vlans_info += f'VLAN: {vlan[0]}\n'
        for port in range_to_numbers(vlan[2]):
            # Добавляем вланы на порты
            ports_vlan[port].append(vlan[0])
    interfaces_vlan = []    # итоговый список (интерфейсы и вланы)

    for line in interfaces:
        max_letters_in_string = 35  # Ограничение на кол-во символов в одной строке в столбце VLAN's
        vlans_compact_str = ''  # Строка со списком VLANов с переносами
        line_str = ''
        for part in ports_vlan[int(findall(r'\d+', line[0])[0])]:
            if len(line_str) + len(part) <= max_letters_in_string:
                line_str += f'{part},'
            else:
                vlans_compact_str += f'{line_str}\n'
                line_str = f'{part},'
        else:
            vlans_compact_str += line_str[:-1]
        interfaces_vlan.append(line + [vlans_compact_str])
    return vlans_info, interfaces_vlan
