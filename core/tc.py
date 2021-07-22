#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Union
from re import findall
import pexpect
import sys
import yaml
import ipaddress
from vendors import *

root_dir = sys.path[0]


def ip_range(ip_input_range_list: list):
    result = []
    for ip_input_range in ip_input_range_list:
        if '/' in ip_input_range:
            try:
                ip = ipaddress.ip_network(ip_input_range)
            except ValueError:
                ip = ipaddress.ip_interface(ip_input_range).network
            return [str(i) for i in list(ip.hosts())]
        range_ = {}
        ip = ip_input_range.split('.')
        for num, oct in enumerate(ip, start=1):
            if '-' in oct:
                ip_range = oct.split('-')
                ip_range[0] = ip_range[0] if 0 <= int(ip_range[0]) < 256 else 0
                ip_range[1] = ip_range[0] if 0 <= int(ip_range[1]) < 256 else 0
                range_[num] = oct.split('-')
            elif 0 <= int(oct) < 256:
                range_[num] = [oct, oct]
            else:
                range_[num] = [0, 0]

        for oct1 in range(int(range_[1][0]), int(range_[1][1])+1):
            for oct2 in range(int(range_[2][0]), int(range_[2][1])+1):
                for oct3 in range(int(range_[3][0]), int(range_[3][1])+1):
                    for oct4 in range(int(range_[4][0]), int(range_[4][1])+1):
                        result.append(f'{oct1}.{oct2}.{oct3}.{oct4}')
    return result


class TelnetConnect:
    def __init__(self, ip: str, device_name: str = ''):
        self.device: dict = {
            'ip': ip,
            'name': device_name,
            'vendor': '',
            'model': '',
            'interfaces': [],
            'mac': '00:00:00:00:00:00'
        }
        self.auth_mode: str = 'default'
        self.auth_file: str = f'{root_dir}/auth.yaml'
        self.auth_group: Union[str, None] = None
        self.login: list = []
        self.password: list = []
        self.privilege_mode_password: str = 'enable'
        self.telnet_session = None
        self.raw_interfaces: list = []
        self.device_info: Union[str, None] = None
        self.mac_last_result: Union[str, None] = None
        self.vlans: Union[list, None] = None
        self.vlan_info: Union[str, None] = None
        self.cable_diag: Union[str, None] = None

    def __del__(self):
        self.close()

    def set_authentication(self, mode: str = 'mixed',
                           auth_file: str = f'{root_dir}/auth.yaml',
                           auth_group: str = None,
                           login: Union[str, list, None] = None,
                           password: Union[str, list, None] = None,
                           privilege_mode_password: str = None) -> None:
        self.auth_mode = mode
        self.auth_file = auth_file
        self.auth_group = auth_group

        if self.auth_mode.lower() == 'group':
            try:
                with open(self.auth_file, 'r') as file:
                    auth_dict = yaml.safe_load(file)
                iter_dict = auth_dict['GROUPS'][self.auth_group.upper()]
                self.login = (iter_dict['login'] if isinstance(iter_dict['login'], list)
                              else [iter_dict['login']]) if iter_dict.get('login') else ['admin']
                # Логин равен списку паролей найденных в элементе 'password' или 'admin'
                self.password = (iter_dict['password'] if isinstance(iter_dict['password'], list)
                                 else [iter_dict['password']]) if iter_dict.get('password') else ['admin']
                self.privilege_mode_password = iter_dict['privilege_mode_password'] if iter_dict.get(
                    'privilege_mode_password') else 'enable'
            except Exception:
                pass

        if self.auth_mode.lower() == 'auto':
            try:
                with open(self.auth_file, 'r') as file:
                    auth_dict = yaml.safe_load(file)
                for group in auth_dict["GROUPS"]:
                    iter_dict = auth_dict["GROUPS"][group]  # Записываем группу в отдельзую переменную
                    # Если есть ключ 'devices_by_name' и в нем имеется имя устройства ИЛИ
                    # есть ключ 'devices_by_ip' и в нем имеется IP устройства
                    if (iter_dict.get('devices_by_name') and self.device["name"] in iter_dict.get('devices_by_name')) \
                            or (iter_dict.get('devices_by_ip') and self.device["ip"] in ip_range(iter_dict.get('devices_by_ip'))):
                        # Логин равен списку логинов найденных в элементе 'login' или 'admin'
                        self.login = (iter_dict['login'] if isinstance(iter_dict['login'], list)
                                      else [iter_dict['login']]) if iter_dict.get('login') else ['admin']
                        # Логин равен списку паролей найденных в элементе 'password' или 'admin'
                        self.password = (iter_dict['password'] if isinstance(iter_dict['password'], list)
                                         else [iter_dict['password']]) if iter_dict.get('password') else ['admin']
                        self.privilege_mode_password = iter_dict['privilege_mode_password'] if iter_dict.get(
                            'privilege_mode_password') else 'enable'

                        break
            except Exception:
                pass

        if login and password:
            self.login = login if isinstance(login, list) else [login]
            self.password = password if isinstance(password, list) else [password]
            self.privilege_mode_password = privilege_mode_password if privilege_mode_password else 'enable'

        if self.auth_mode == 'mixed':
            try:
                with open(self.auth_file, 'r') as file:
                    auth_dict = yaml.safe_load(file)
                self.login = auth_dict['MIXED']['login']
                self.password = auth_dict['MIXED']['password']
                self.privilege_mode_password = auth_dict['MIXED']['privilege_mode_password'] if auth_dict['MIXED'].get(
                    'privilege_mode_password') else 'enable'

            except Exception:
                pass

    def get_device_model(self):
        self.telnet_session.sendline('show version')
        self.telnet_session.expect('show version')
        version = ''
        while True:
            m = self.telnet_session.expect(
                [
                    r']$',
                    '-More-',
                    r'>\s*$',
                    r'#\s*$',
                    pexpect.TIMEOUT
                ]
            )

            version += str(self.telnet_session.before.decode('utf-8'))
            if m == 1:
                self.telnet_session.send(' ')
            elif m == 4:
                self.telnet_session.sendcontrol('C')
            else:
                break
        model = ''
        # ZTE
        if ' ZTE Corporation:' in version:
            self.device["vendor"] = 'zte'
            model = findall(r'Module 0:\s+([\S\W]);\sfasteth', version)

        # HUAWEI
        if 'Unrecognized command' in version:
            self.device["vendor"] = 'huawei'
            model = findall(
                r'Quidway\s+(\S+)\s+.*uptime is',
                huawei.send_command(
                    telnet_session=self.telnet_session,
                    command='display version',
                    prompt=r'<\S+>|\[\S+\]'
                )
            )

        # CISCO
        if 'cisco' in version.lower():
            model = findall(r'Model number\s+:\s+(\S+)', version)
            self.device["vendor"] = f"cisco"

        # D_LINK
        if 'Next possible completions:' in version:
            self.device["vendor"] = 'd-link'
            model = findall(
                r'Device Type\s+:\s+(\S+)\s',
                d_link.send_command(
                    session=self.telnet_session,
                    command='show switch',
                    privilege_mode_password=self.privilege_mode_password
                )
            )

        # ALCATEL
        if findall(r'SW version\s+', version):
            self.device["vendor"] = 'alcatel_or_lynksys'

        if 'Hardware version' in version:
            self.device["vendor"] = 'edge-core'
        if 'Active-image:' in version:
            self.device["vendor"] = 'eltex-mes'
            model = findall(
                r'System Description:\s+(\S+)',
                eltex.send_command(
                    session=self.telnet_session,
                    command='show system'
                )
            )

        if 'Boot version:' in version:
            self.device["vendor"] = 'eltex-esr'
            model = findall(
                r'System type:\s+Eltex\s(\S+)\s',
                eltex.send_command(
                    session=self.telnet_session,
                    command='show system | include \"System type\"'
                )
            )

        if 'ExtremeXOS' in version:
            self.device["vendor"] = 'extreme'
            model = findall(
                r'System Type:\s+(\S+)',
                extreme.send_command(
                    session=self.telnet_session,
                    command='show switch | include \"System Type\"'
                )
            )

        if 'QTECH' in version:
            self.device["vendor"] = 'q-tech'
            model = findall(
                r'\s*(\S+)\sDevice',
                extreme.send_command(
                    session=self.telnet_session,
                    command='show version | include Device'
                )
            )

        if '% Unknown command' in version:
            self.telnet_session.sendline('display version')
            while True:
                m = self.telnet_session.expect([r']$', '---- More', r'>$', r'#', pexpect.TIMEOUT, '{'])
                if m == 5:
                    self.telnet_session.expect('}:')
                    self.telnet_session.sendline('\n')
                    continue
                version += str(self.telnet_session.before.decode('utf-8'))
                if m == 1:
                    self.telnet_session.sendline(' ')
                if m == 4:
                    self.telnet_session.sendcontrol('C')
                else:
                    break
            if findall(r'VERSION : MA\d+', version):
                self.device["vendor"] = 'huawei-msan'
                model = findall(r'VERSION : (\S+)', version)
        if 'show: invalid command, valid commands are' in version:
            self.telnet_session.sendline('sys info show')
            while True:
                m = self.telnet_session.expect([r']$', '---- More', r'>\s*$', r'#\s*$', pexpect.TIMEOUT])
                version += str(self.telnet_session.before.decode('utf-8'))
                if m == 1:
                    self.telnet_session.sendline(' ')
                if m == 4:
                    self.telnet_session.sendcontrol('C')
                else:
                    break
            if 'ZyNOS version' in version:
                self.device["vendor"] = 'zyxel'

        if model:
            self.device["model"] = model[0]
        return self.device["vendor"]

    def close(self):
        self.telnet_session.close()

    def connect(self) -> bool:
        if not self.login or not self.password:
            self.set_authentication()
        connected = False
        self.telnet_session = pexpect.spawn(f'telnet {self.device["ip"]}')
        try:
            for login, password in zip(self.login+['admin'], self.password+['admin']):
                while not connected:  # Если не авторизировались
                    login_stat = self.telnet_session.expect(
                        [
                            r"[Ll]ogin(?![-\siT]).*:\s*$",  # 0
                            r"[Uu]ser\s(?![lfp]).*:\s*$",   # 1
                            r"[Nn]ame.*:\s*$",              # 2
                            r'[Pp]ass.*:\s*$',              # 3
                            r'Connection closed',           # 4
                            r'Unable to connect',           # 5
                            r'[#>\]]\s*$',                  # 6
                            r'press ENTER key to retry authentication'  # 7
                        ],
                        timeout=40
                    )
                    if login_stat == 7:
                        self.telnet_session.sendline('\n')
                        continue
                    if login_stat < 3:
                        self.telnet_session.sendline(login)  # Вводим логин
                        continue
                    if 4 <= login_stat <= 5:
                        print(f'    Telnet недоступен! {self.device["name"]} ({self.device["ip"]})')
                        return False
                    if login_stat == 3:
                        self.telnet_session.sendline(password)  # Вводим пароль
                    if login_stat >= 6:  # Если был поймал символ начала ввода команды
                        connected = True  # Подключились
                    break  # Выход из цикла

                if connected:
                    break
            else:  # Если не удалось зайти под логинами и паролями из списка аутентификации
                print(f'    Неверный логин или пароль! {self.device["name"]} ({self.device["ip"]})')
                return False

            self.device["vendor"] = self.get_device_model()
            return True

        except pexpect.exceptions.TIMEOUT:
            print(f'    Время ожидания превышено! (timeout) {self.device["name"]} ({self.device["ip"]})')
            return False

    def isalive(self):
        try:
            return bool(self.get_device_model())
        except pexpect.EOF:
            return False
        except pexpect.TIMEOUT:
            return False

    def get_interfaces(self):
        """
        Собирает информацию о состоянии интерфейсов
        :return: {"interface", "status", "description"}, .. , {..}
        """
        if 'cisco' in self.device["vendor"]:
            self.raw_interfaces = cisco.show_interfaces(telnet_session=self.telnet_session)
            self.device["interfaces"] = [
                {'interface': line[0], 'status': line[1], 'description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'd-link' in self.device["vendor"]:
            self.raw_interfaces = d_link.show_interfaces(
                telnet_session=self.telnet_session,
                privilege_mode_password=self.privilege_mode_password
            )
            self.device["interfaces"] = [
                {'interface': line[0], 'status': line[1], 'description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'huawei' in self.device["vendor"]:
            self.raw_interfaces = huawei.show_interfaces(
                telnet_session=self.telnet_session,
                privilege_mode_password=self.privilege_mode_password
            )
            self.device["interfaces"] = [
                {'interface': line[0], 'status': line[1], 'description': line[2]}
                for line in self.raw_interfaces
            ]
        if 'zte' in self.device["vendor"]:
            self.raw_interfaces = zte.show_interfaces(telnet_session=self.telnet_session)
            self.device["interfaces"] = [
                {'interface': line[0], 'status': line[1], 'description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'alcatel' in self.device["vendor"] or 'lynksys' in self.device["vendor"]:
            interfaces_list = alcatel_linksys.show_interfaces(telnet_session=self.telnet_session)
            self.device["interfaces"] = [
                {'interface': line[0], 'status': line[1], 'description': line[3]}
                for line in interfaces_list
            ]
        if 'edge-core' in self.device["vendor"]:
            self.raw_interfaces = edge_core.show_interfaces(telnet_session=self.telnet_session)
            self.device["interfaces"] = [
                {'interface': line[0], 'status': line[1], 'description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'eltex' in self.device["vendor"]:
            self.raw_interfaces = eltex.show_interfaces(
                telnet_session=self.telnet_session,
                eltex_type=self.device["vendor"]
            )
            self.device["interfaces"] = [
                {'interface': line[0], 'status': line[1], 'description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'extreme' in self.device["vendor"]:
            self.raw_interfaces = extreme.show_interfaces(telnet_session=self.telnet_session)
            self.device["interfaces"] = [
                {'interface': line[0], 'status': line[1], 'description': line[3]}
                for line in self.raw_interfaces
            ]
        if 'q-tech' in self.device["vendor"]:
            self.raw_interfaces = qtech.show_interfaces(telnet_session=self.telnet_session)
            self.device["interfaces"] = [
                {'interface': line[0], 'status': line[1], 'description': line[2]}
                for line in self.raw_interfaces
            ]
        return self.device["interfaces"]

    def set_port_status(self, port: str, status: str):
        if 'cisco' in self.device["vendor"]:
            return cisco.set_port_status(
                session=self.telnet_session,
                port=port,
                status=status
            )
        if 'eltex-mes' in self.device["vendor"]:
            return eltex.set_port_status(
                session=self.telnet_session,
                port=port,
                status=status
            )
        if 'huawei' in self.device["vendor"]:
            return huawei.set_port_status(
                session=self.telnet_session,
                port=port,
                status=status,
                privilege_mode_password=self.privilege_mode_password
            )
        if 'd-link' in self.device["vendor"]:
            return d_link.set_port_status(
                session=self.telnet_session,
                port=port,
                status=status,
                privilege_mode_password=self.privilege_mode_password
            )
        if 'alcatel' in self.device["vendor"] or 'lynksys' in self.device["vendor"]:
            return alcatel_linksys.set_port_status(
                session=self.telnet_session,
                port=port,
                status=status
            )

    def save_running_configuration(self):
        if 'cisco' in self.device["vendor"]:
            return cisco.save_running_configuration(session=self.telnet_session)
        if 'eltex-mes' in self.device["vendor"]:
            return eltex.save_running_configuration(session=self.telnet_session)
        if 'huawei' in self.device["vendor"]:
            return huawei.save_running_configuration(
                session=self.telnet_session,
                privilege_mode_password=self.privilege_mode_password
            )
        if 'd-link' in self.device["vendor"]:
            return d_link.save_running_configuration(
                session=self.telnet_session,
                privilege_mode_password=self.privilege_mode_password
            )
        if 'alcatel' in self.device["vendor"] or 'lynksys' in self.device["vendor"]:
            return alcatel_linksys.save_running_configuration(self.telnet_session)
