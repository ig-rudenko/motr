import pexpect
from re import findall, sub
import sys
import textfsm
from core.intf_view import interface_normal_view

root_dir = sys.path[0]


def save_running_configuration(session):
    """
    Сохраняет текущую конфигурацию в стартовую

    :param session:     Залогиненная сессия удаленного терминала
    :return:            True - конфигурация сохранена, False - конфигурацию не удалось сохранить
    """
    try:
        session.sendline('write')
        session.expect(r'write')
        if session.expect([r'Building', 'Invalid input']):
            session.sendline('do write')
            print('(config)# do write')
        else:
            print('# write')
        print('Building configuration...')
        if session.expect([r'\[OK\]', pexpect.TIMEOUT]):
            print('Timeout while saving configuration')
            return False
        session.expect(r'\S+#$')
        print('Configuration saved!')
        return True
    except pexpect.TIMEOUT:
        print('Timeout!')
        return False
    except pexpect.EOF:
        print('Потеряна связь с оборудованием')
        return False


def set_port_status(session, port: str, status: str) -> bool:
    try:
        session.sendline('configure terminal')
        print('# configure terminal')
        session.sendline(f'interface {interface_normal_view(port)}')
        print(f'(config)# interface {interface_normal_view(port)}')
        if session.expect([r'\S+\(config-if\)#$', pexpect.TIMEOUT]):
            return False    # Не удалось зайти на интерфейс (таймаут)
        if status == 'enable':
            session.sendline('no shutdown')
            print('(config-if)# no shutdown')
        elif status == 'disable':
            session.sendline('shutdown')
            print('(config-if)# shutdown')
        session.expect(r'\S+\(config-if\)#$')
        session.sendline('exit')
        print('(config-if)# exit')
        session.expect(r'\S+\(config\)#$')
        print('(config)# exit')
        session.sendline('exit')
        print('# ')
        session.expect(r'\S+#$')
        return True
    except pexpect.TIMEOUT:
        print('Timeout!')
        return False
    except pexpect.EOF:
        print('Потеряна связь с оборудованием')
        return False


def send_command(session, command: str, prompt: str = r'\S+#$', next_catch: str = None, expect: bool = True):
    output = ''
    session.sendline(command)
    # print(f'?#{command}')
    if not expect:
        return True
    session.expect(command[-30:])
    if next_catch:
        session.expect(next_catch)
    while True:
        match = session.expect(
            [
                prompt,             # 0 - конец
                "--More--",         # 1 - далее
                pexpect.TIMEOUT     # 2
            ]
        )
        page = str(session.before.decode('utf-8')).replace("[42D", '').replace(
            "        ", '')
        output += page.strip()
        if match == 0:
            break
        elif match == 1:
            session.send(" ")
            output += '\n'
        else:
            print("    Ошибка: timeout")
            break
    return output


def show_mac(telnet_session, interfaces: list, interface_filter: str) -> str:

    intf_to_check = []  # Интерфейсы для проверки
    mac_output = ''  # Вывод MAC
    not_uplinks = True if interface_filter == 'only-abonents' else False

    for line in interfaces:
        if (
                (not not_uplinks and bool(findall(interface_filter, line[3])))  # интерфейсы по фильтру
                or (not_uplinks and  # ИЛИ все интерфейсы, кроме:
                    'SVSL' not in line[3].upper() and  # - интерфейсов, которые содержат "SVSL"
                    'POWER_MONITORING' not in line[3].upper())  # - POWER_MONITORING
                and not ('down' in line[2].lower() and not line[3])  # - пустые интерфейсы с LinkDown
                and 'down' not in line[1].lower()  # И только интерфейсы со статусом admin up
                and 'VL' not in line[0].upper()  # И не VLAN'ы
        ):  # Если описание интерфейсов удовлетворяет фильтру
            intf_to_check.append([line[0], line[3]])

    if not intf_to_check:
        if not_uplinks:
            return 'Порты абонентов не были найдены либо имеют статус admin down (в этом случае MAC\'ов нет)'
        else:
            return f'Ни один из портов не прошел проверку фильтра "{interface_filter}" ' \
                   f'либо имеет статус admin down (в этом случае MAC\'ов нет)'

    for intf in intf_to_check:  # для каждого интерфейса
        telnet_session.sendline(f'show mac address-table interface {interface_normal_view(intf[0])}')
        telnet_session.expect(f'-------------------')
        telnet_session.expect('Vla')
        separator_str = '─' * len(f'Интерфейс: {interface_normal_view(intf[1])}')
        mac_output += f'\n    Интерфейс: {interface_normal_view(intf[1])}\n' \
                      f'    {separator_str}\n' \
                      f'Vla'
        while True:
            match = telnet_session.expect(
                [
                    'Total Mac Addresses',  # 0 - найдены все MAC адреса
                    r'#$',                  # 1 - конец
                    "--More--",             # 2 - Далее
                    pexpect.TIMEOUT         # 3
                ]
            )
            page = str(telnet_session.before.decode('utf-8')).replace("[42D", '').replace(
                "        ", '')
            mac_output += page.strip()
            if match <= 1:
                break
            elif match == 2:
                telnet_session.send(" ")
                mac_output += '\n'
            else:
                print("    Ошибка: timeout")
                break
        mac_output += '\n\n'
    return mac_output


def show_interfaces(telnet_session) -> list:
    output = send_command(
        session=telnet_session,
        command='show int des'
    )
    output = sub('.+\nInterface', 'Interface', output)
    with open(f'{root_dir}/templates/int_des_cisco.template', 'r') as template_file:
        int_des_ = textfsm.TextFSM(template_file)
        result = int_des_.ParseText(output)  # Ищем интерфейсы

    return [line for line in result if not line[0].startswith('V')]


def get_device_info(telnet_session):
    version = send_command(
        session=telnet_session,
        command='show version'
    )
    version = sub(r'\W+This product [\W\S]+cisco\.com\.', '', version)
    version += '\n'

    # ENVIRONMENT
    environment = send_command(
        session=telnet_session,
        command='show environment'
    )
    if 'Invalid input' in environment:
        environment = send_command(
            session=telnet_session,
            command='show env all'
        )
    environment = f"""
   ┌──────────────────────────────────┐
   │ Температура, Питание, Охлаждение │
   └──────────────────────────────────┘
{environment}
"""
    if 'Invalid input' in environment:
        environment = ''
    version += environment

    # INVENTORY
    inventory = send_command(
            session=telnet_session,
            command='show inventory oid'
        )
    if findall(r'Invalid input|% No entity', inventory):
        inventory = send_command(
            session=telnet_session,
            command='show inventory'
        )
    inventory = f"""
    ┌────────────────┐
    │ Инвентаризация │
    └────────────────┘
{inventory}
"""
    if findall(r'Invalid input|% No entity', inventory):
        inventory = ''
    version += inventory

    # SNMP
    snmp_info = send_command(
            session=telnet_session,
            command='show snmp'
        )
    version += f"""
    ┌──────┐
    │ SNMP │
    └──────┘
{snmp_info}
"""
    # IDPROMs
    extended_tech_info = send_command(
            session=telnet_session,
            command='show idprom all'
        )

    extended_tech_info = f"""
    ┌                                    ┐
    │ Расширенная техническая информация │
    └                                    ┘
                      ▼
{extended_tech_info}
    """
    if '% Invalid input' in extended_tech_info:
        extended_tech_info = ''
    version += extended_tech_info

    # mac_address = findall(r'MAC Address\s+:\s+(\S\S:\S\S:\S\S:\S\S:\S\S:\S\S)', version)
    # serial_number = findall(r'System serial number\s+:\s+(\S+)', version)

    return version


def show_vlans(telnet_session, interfaces) -> tuple:
    result = []
    for line in interfaces:
        if not line[0].startswith('V'):
            output = send_command(
                session=telnet_session,
                command=f"show running-config interface {interface_normal_view(line[0])}",
                next_catch="Building configuration.."
            )
            vlans_group = findall(r'vlan [add ]*(\S*\d)', output)   # Строчки вланов
            switchport_mode = findall(r'switchport mode (\S+)', output)  # switchport mode
            max_letters_in_string = 35  # Ограничение на кол-во символов в одной строке в столбце VLAN's
            vlans_compact_str = ''      # Строка со списком VLANов с переносами
            line_str = ''
            for part in ','.join(switchport_mode + vlans_group).split(','):
                if len(line_str) + len(part) <= max_letters_in_string:
                    line_str += f'{part},'
                else:
                    vlans_compact_str += f'{line_str}\n'
                    line_str = f'{part},'
            else:
                vlans_compact_str += line_str[:-1]

            result.append(line + [vlans_compact_str])

    vlans_info = send_command(
        session=telnet_session,
        command='show vlan brief'
    )
    with open(f'{root_dir}/templates/vlans_templates/cisco_vlan_info.template', 'r') as template_file:
        vlans_info_template = textfsm.TextFSM(template_file)
        vlans_info_table = vlans_info_template.ParseText(vlans_info)  # Ищем интерфейсы

    return vlans_info_table, result
