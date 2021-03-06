import pexpect
from re import findall, sub
import sys
import textfsm
from core.intf_view import interface_normal_view

root_dir = sys.path[0]


def save_running_configuration(session) -> bool:
    """
    Сохраняет текущую конфигурацию в стартовую

    :param session:     Залогиненная сессия удаленного терминала
    :return:            True - конфигурация сохранена, False - конфигурацию не удалось сохранить
    """
    try:
        session.sendline('write')
        session.expect(r'write')
        if session.expect([r'Overwrite file', 'Unrecognized command']):
            session.sendline('do write')
            print('(config)#do write')
            session.expect(r'Overwrite file')
        else:
            print('#write')

        session.sendline('Y')   # Подтверждаем сохранение
        if session.expect([r'Copy succeeded', pexpect.TIMEOUT], timeout=10):
            print('Timeout while saving configuration')     # Если ушли в таймаут
            return False
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
        print('#configure terminal')
        session.sendline(f'interface {interface_normal_view(port)}')
        print(f'(config)#interface {interface_normal_view(port)}')
        if session.expect([r'\S+\(config-if\)#$', pexpect.TIMEOUT]):
            return False    # Не удалось зайти на интерфейс (таймаут)
        if status == 'enable':
            session.sendline('no shutdown')
            print('(config-if)#no shutdown')
        elif status == 'disable':
            session.sendline('shutdown')
            print('(config-if)#shutdown')
        session.expect(r'\S+\(config-if\)#$')
        session.sendline('exit')
        session.expect(r'\S+\(config\)#$')
        print('(config)#')
        session.sendline('exit')
        session.expect(r'\S+#$')
        print('#')
        return True
    except pexpect.TIMEOUT:
        print('Timeout!')
        return False
    except pexpect.EOF:
        print('Потеряна связь с оборудованием')
        return False


def send_command(session, command: str, prompt: str = r'\S+#\s*$', next_catch: str = None, expect: bool = True):
    output = ''
    session.sendline(command)
    # print(f'?#{command}')
    if not expect:
        return True
    session.expect(command[-30:])
    if next_catch:
        session.expect(next_catch)
        # print(f'..{next_catch}..')
    while True:
        match = session.expect(
            [
                prompt,
                r"More: <space>,  Quit: q or CTRL\+Z, One line: <return> ",
                pexpect.TIMEOUT
            ]
        )
        output += session.before.decode('utf-8').strip()
        if match == 0:
            break
        elif match == 1:
            session.send(" ")
            output += '\n'
        else:
            print("    Ошибка: timeout")
            break
    return output


def show_interfaces(telnet_session, eltex_type: str = 'eltex-mes') -> str:
    telnet_session.sendline("show int des")
    telnet_session.expect("show int des")
    output = ''
    while True:
        match = telnet_session.expect(
            [
                r'\S+#\s*$',
                r"More: <space>,  Quit: q or CTRL\+Z, One line: <return> ",
                pexpect.TIMEOUT
            ]
        )
        output += telnet_session.before.decode('utf-8').strip()
        if 'Ch       Port Mode (VLAN)' in output:
            telnet_session.sendline('q')
            telnet_session.expect(r'\S+#\s*$')
            break
        if match == 0:
            break
        elif match == 1:
            telnet_session.send(" ")
        else:
            print("    Ошибка: timeout")
            break
    with open(f'{root_dir}/templates/int_des_{eltex_type}.template', 'r') as template_file:
        int_des_ = textfsm.TextFSM(template_file)
        result = int_des_.ParseText(output)  # Ищем интерфейсы
    return result


def show_mac_esr_12vf(telnet_session) -> str:
    # Для Eltex ESR-12VF выводим всю таблицу MAC адресов
    mac_output = ''
    telnet_session.sendline(f'show mac address-table ')
    telnet_session.expect(r'\S+# ')
    m_output = sub(r'.+\nVID', 'VID', str(telnet_session.before.decode('utf-8')))
    mac_output += f"\n{m_output}"
    return mac_output


def show_mac(telnet_session, interfaces: list, interface_filter: str, eltex_type: str = 'eltex-mes') -> str:
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
        ):  # Если описание интерфейсов удовлетворяет фильтру
            intf_to_check.append([line[0], line[3]])

    if not intf_to_check:
        if not_uplinks:
            return 'Порты абонентов не были найдены либо имеют статус admin down (в этом случае MAC\'ов нет)'
        else:
            return f'Ни один из портов не прошел проверку фильтра "{interface_filter}" ' \
                   f'либо имеет статус admin down (в этом случае MAC\'ов нет)'

    for intf in intf_to_check:  # для каждого интерфейса
        separator_str = '─' * len(f'Интерфейс: {intf[1]}')
        mac_output += f'\n    Интерфейс: {intf[1]}\n    {separator_str}\n'

        if 'eltex-mes' in eltex_type:
            telnet_session.sendline(f'show mac address-table interface {interface_normal_view(intf[0])}')
            telnet_session.expect(r'Aging time is \d+ \S+')
            while True:
                match = telnet_session.expect(
                    [
                        r'\S+#\s*$',
                        r"More: <space>,  Quit: q or CTRL\+Z, One line: <return> ",
                        pexpect.TIMEOUT
                    ]
                )
                page = telnet_session.before.decode('utf-8')
                mac_output += f"    {page.strip()}"
                if match == 0:
                    break
                elif match == 1:
                    telnet_session.send(" ")
                else:
                    print("    Ошибка: timeout")
                    break
            mac_output = sub(r'(?<=\d)(?=\S\S:\S\S:\S\S:\S\S:\S\S:\S\S)', r'     ', mac_output)
            mac_output = sub(r'Vlan\s+Mac\s+Address\s+Port\s+Type',
                             'Vlan          Mac_Address         Port       Type',
                             mac_output)
            mac_output += '\n'

        if 'eltex-esr' in eltex_type:
            mac_output += "VID     MAC Address          Interface                        Type \n" \
                          "-----   ------------------   ------------------------------   -------"
            mac_output += send_command(
                session=telnet_session,
                command=f'show mac address-table interface {interface_normal_view(intf[0])} |'
                        f' include \"{interface_normal_view(intf[0]).lower()}\"'
            )

    return mac_output


def show_device_info(telnet_session):
    info = ''

    # SYSTEM ID
    telnet_session.sendline('show system id')
    telnet_session.expect(r'show system id\W+')
    telnet_session.expect(r'\W+\S+#')
    info += telnet_session.before.decode('utf-8')
    info += '\n\n'

    # VERSION
    telnet_session.sendline('show system')
    telnet_session.expect(r'show system')
    telnet_session.expect(r'\W+\S+#')
    info += telnet_session.before.decode('utf-8')
    info += '\n\n'

    # CPU
    telnet_session.sendline('show cpu utilization')
    telnet_session.expect(r'show cpu utilization')
    telnet_session.expect(r'\S+#')
    info += '   ┌──────────────┐\n'
    info += '   │ ЗАГРУЗКА CPU │\n'
    info += '   └──────────────┘\n'
    info += telnet_session.before.decode('utf-8')
    info += '\n\n'

    # SNMP
    telnet_session.sendline('show snmp')
    telnet_session.expect(r'show snmp\W+')
    telnet_session.expect(r'\W+\S+#$')
    info += '   ┌──────┐\n'
    info += '   │ SNMP │\n'
    info += '   └──────┘\n'
    info += telnet_session.before.decode('utf-8')
    info += '\n\n'
    return info


def show_vlans(telnet_session, interfaces) -> tuple:
    result = []
    for line in interfaces:
        if not line[0].startswith('V'):
            output = send_command(
                session=telnet_session,
                command=f'show running-config interface {interface_normal_view(line[0])}'
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
        command='show vlan'
    )

    with open(f'{root_dir}/templates/vlans_templates/eltex_vlan_info.template', 'r') as template_file:
        vlans_info_template = textfsm.TextFSM(template_file)
        vlans_info_table = vlans_info_template.ParseText(vlans_info)  # Ищем интерфейсы

    return vlans_info_table, result
