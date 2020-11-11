
import pexpect
from main.logs import lprint         # Запись логов
import re
from re import findall
import textfsm
import subprocess
from concurrent.futures import ThreadPoolExecutor   # Многопоточность
import os
import sys

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])


def interfaces(current_ring: dict, checking_device_name: str, enable_print: bool = True):
    """
    Подключаемся к оборудованию по telnet и считываем интерфейсы, их статусы и описание
    Автоматически определяется тип производителя \n
    :param current_ring:            Кольцо
    :param checking_device_name:    Имя оборудования
    :param enable_print:            По умолчанию вывод в консоль включен
    :return:                        Список: интерфейс, статус, описание; False в случае ошибки
    """
    with pexpect.spawn(f"telnet {current_ring[checking_device_name]['ip']}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                if enable_print:
                    lprint("    \033[31mTelnet недоступен!\033[0m")
                return False
            telnet.sendline(current_ring[checking_device_name]["user"])
            if enable_print:
                lprint(f"    Подключаемся к {checking_device_name} ({current_ring[checking_device_name]['ip']})")
            telnet.expect("[Pp]ass")
            telnet.sendline(current_ring[checking_device_name]["pass"])
            match = telnet.expect([']', '>', '#', 'Failed to send authen-req'])
            if match == 3:
                if enable_print:
                    lprint('    \033[31mНеверный логин или пароль!\033[0m')
                return False
            else:
                telnet.sendline('show version')
                version = ''
                while True:
                    m = telnet.expect([r']$', '-More-', r'>$', r'#'])
                    version += str(telnet.before.decode('utf-8'))
                    if m == 1:
                        telnet.sendline(' ')
                    else:
                        break
                # ZTE
                if bool(findall(r' ZTE Corporation:', version)):
                    if enable_print:
                        lprint("    Тип оборудования: ZTE")

                # Huawei
                elif bool(findall(r'Unrecognized command', version)):
                    if enable_print:
                        lprint("    Тип оборудования: Huawei")
                    telnet.sendline("dis int des")
                    output = ''
                    num = ''
                    while True:
                        match = telnet.expect(['Too many parameters', ']', "  ---- More ----",
                                               "Unrecognized command", ">", pexpect.TIMEOUT])
                        output += str(telnet.before.decode('utf-8')).replace("[42D", '').strip()
                        # page = re.sub(" +\x08+ +\x08+", "\n", page)
                        if match == 4:
                            telnet.sendline("quit")
                            break
                        elif match == 1:
                            telnet.sendline("quit")
                            telnet.sendline("quit")
                            break
                        elif match == 2:
                            telnet.send(" ")
                            output += '\n'
                        elif match == 0 or match == 3:
                            telnet.expect('>')
                            telnet.sendline('super')
                            telnet.expect(':')
                            telnet.sendline('sevaccess')
                            telnet.expect('>')
                            telnet.sendline('dis brief int')
                            num = '2'
                            output = ''
                        else:
                            if enable_print:
                                lprint("    Ошибка: timeout")
                            break
                    telnet.sendline("quit")
                    output = re.sub("\n +\n", "\n", output)
                    with open(f'{root_dir}/templates/int_des_huawei{num}.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result = int_des_.ParseText(output)  # Ищем интерфейсы
                    return result

                # Cisco
                elif bool(findall(r'Cisco IOS', version)):
                    if enable_print:
                        lprint("    Тип оборудования: Cisco")
                    if match == 1:
                        telnet.sendline('enable')
                        telnet.expect('[Pp]ass')
                        telnet.sendline('sevaccess')
                    telnet.expect('#')
                    telnet.sendline("sh int des")
                    output = ''
                    while True:
                        match = telnet.expect([r'#$', "--More--", pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8')).replace("[42D", '').replace(
                            "        ", '')
                        # page = re.sub(" +\x08+ +\x08+", "\n", page)
                        output += page.strip()
                        if match == 0:
                            telnet.sendline("exit")
                            break
                        elif match == 1:
                            telnet.send(" ")
                            output += '\n'
                        else:
                            if enable_print:
                                lprint("    Ошибка: timeout")
                            break
                    output = re.sub("\n +\n", "\n", output)
                    with open(f'{root_dir}/templates/int_des_cisco.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result = int_des_.ParseText(output)  # Ищем интерфейсы
                    return result

                # D-Link
                elif bool(findall(r'Next possible completions:', version)):
                    if enable_print:
                        lprint("    Тип оборудования: D-Link")
                    telnet.sendline('enable admin')
                    if telnet.expect(["#", "[Pp]ass"]):
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
                    if enable_print:
                        lprint("    Тип оборудования: Alcatel or Linksys")
                    telnet.sendline('show interfaces configuration')
                    port_state = ''
                    while True:
                        match = telnet.expect(['More: <space>', '#', pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8'))
                        port_state += page.strip()
                        if match == 0:
                            telnet.sendline(' ')
                        elif match == 1:
                            break
                        else:
                            if enable_print:
                                lprint("    Ошибка: timeout")
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
                            telnet.sendline('exit')
                            break
                        else:
                            if enable_print:
                                lprint("    Ошибка: timeout")
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
                    if enable_print:
                        lprint("    Тип оборудования: Edge-Core")
                    telnet.sendline('show running-config')
                    output = ''
                    while True:
                        match = telnet.expect(['---More---', '#', pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8'))
                        output += page.strip()
                        if match == 0:
                            telnet.sendline(' ')
                        elif match == 1:
                            break
                        else:
                            if enable_print:
                                lprint("    Ошибка: timeout")
                            break
                    result = []
                    intf_raw = findall(r'(interface (.+\n)+?!)', str(output))
                    for x in intf_raw:
                        result.append([findall(r'interface (\S*\s*\S*\d)', str(x))[0],
                                       'admin down' if 'shutdown' in str(x) else 'up',
                                       findall(r'description (\S+)', str(x))[0] if len(
                                           findall(r'description (\S+)', str(x))) > 0 else ''])
                    return result

                # Zyxel
                elif bool(findall(r'ZyNOS', version)):
                    if enable_print:
                        lprint("    Тип оборудования: Zyxel")

                # Eltex
                elif bool(findall(r'Active-image: ', version)):
                    if enable_print:
                        lprint("    Eltex")
                    telnet.sendline("sh int des")
                    output = ''
                    while True:
                        match = telnet.expect([r'#$', "More: <space>", pexpect.TIMEOUT])
                        page = str(telnet.before.decode('utf-8')).replace("[42D", '').replace(
                            "        ", '')
                        # page = re.sub(" +\x08+ +\x08+", "\n", page)
                        output += page.strip()
                        if match == 0:
                            telnet.sendline("exit")
                            break
                        elif match == 1:
                            telnet.send(" ")
                            # output += '\n'
                        else:
                            if enable_print:
                                lprint("    Ошибка: timeout")
                            break
                    output = re.sub("\n +\n", "\n", output)
                    with open(f'{root_dir}/templates/int_des_eltex.template', 'r') as template_file:
                        int_des_ = textfsm.TextFSM(template_file)
                        result = int_des_.ParseText(output)  # Ищем интерфейсы
                    return result

                telnet.sendline('exit')

        except pexpect.exceptions.TIMEOUT:
            if enable_print:
                lprint("    \033[31mВремя ожидания превышено! (timeout)\033[0m")


def search_admin_down(ring: dict, ring_list: list, checking_device_name: str, enable_print=True):
    """
    Ищет есть ли у данного узла сети порт(ы) в состоянии "admin down" в сторону другого узла сети из этого кольца.
    Проверка осуществляется по наличию в description'е имени узла сети из текущего кольца.

    :param ring:                    Кольцо
    :param ring_list:               Список узлов сети в кольце
    :param checking_device_name:    Имя узла сети
    :param enable_print:            Вывод в консоль включен по умолчанию
    :return:    В случае успеха возвращает имя оборудования с портом(ми) "admin down" и имя оборудования к которому
                ведет этот порт и интерфейс. Если нет портов "admin down", то возвращает "False"
    """
    if enable_print:
        lprint("---- def search_admin_down ----")

    result = interfaces(ring, checking_device_name, enable_print=enable_print)
    ad_to_this_host = []  # имя оборудования к которому ведет порт "admin down"
    ad_interface = []
    # lprint(result)
    if result:  # Если найден admin_down, то...
        for dev_name in ring_list:  # ...перебираем узлы сети в кольце:
            for res_line in result:  # Перебираем все найденные интерфейсы:
                if bool(findall(dev_name, res_line[2])) and (
                        bool(findall(r'(admin down|\*down|Down|Disabled|ADM DOWN)', res_line[1]))
                ):
                    # ...это хост, к которому закрыт порт от проверяемого коммутатора
                    ad_to_this_host.append(dev_name)
                    ad_interface.append(res_line[0])  # интерфейс со статусом "admin down"
                    # lprint(checking_device_name, ad_to_this_host, ad_interface)
    if ad_to_this_host and ad_interface:
        return {"device": checking_device_name, "next_device": ad_to_this_host, "interface": ad_interface}
    else:
        return False


def interface_normal_view(interface) -> str:
    """
    Приводит имя интерфейса к виду принятому по умолчанию для коммутаторов\n
    Например: Eth 0/1 -> Ethernet0/1
              GE1/0/12 -> GigabitEthernet1/0/12\n
    :param interface:   Интерфейс в сыром виде (raw)
    :return:            Интерфейс в общепринятом виде
    """
    interface = str(interface)
    interface_number = findall(r'(\d+([/\\]?\d*)*)', str(interface))
    if bool(findall('^[Ee]', interface)):
        return f"Ethernet{interface_number[0][0]}"
    elif bool(findall('^[Ff]', interface)):
        return f"FastEthernet{interface_number[0][0]}"
    elif bool(findall('^[Gg]', interface)):
        return f"GigabitEthernet{interface_number[0][0]}"
    elif bool(findall('^\d+', interface)):
        return findall('^\d+', interface)[0]
    elif bool(findall('^[Tt]', interface)):
        return f'TengigabitEthernet{interface_number[0][0]}'
    else:
        return interface


def set_port_status(current_ring: dict, device: str, interface: str, status: str):
    """
    Заходим на оборудование через telnet и устанавливаем состояние конкретного порта
    :param current_ring"    Кольцо
    :param device:          Имя узла сети, с которым необходимо взаимодействовать
    :param interface:       Интерфейс узла сети
    :param status:          "up": поднять порт, "down": положить порт
    :return:                Статус выполнения или ошибки
    """
    lprint("---- def set_port_status ----")

    try_to_save = 3     # 3 попытки сохранить
    try_to_down = 3     # 3 попытки закрыть порт
    try_to_up = 3       # 3 попытки открыть порт

    with pexpect.spawn(f"telnet {current_ring[device]['ip']}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                lprint("    Telnet недоступен!")
                return 'telnet недоступен'
            telnet.sendline(current_ring[device]["user"])
            lprint(f"    Login to {device}")
            telnet.expect("[Pp]ass")
            telnet.sendline(current_ring[device]["pass"])
            lprint(f"    Pass to {device}")
            match = telnet.expect([']', '>', '#', 'Failed to send authen-req'])
            if match == 3:
                lprint('    Неверный логин или пароль!')
                return 'неверный логин или пароль'

            telnet.sendline('show version')
            version = ''
            while True:
                m = telnet.expect([r']$', '-More-', r'>$', r'#'])
                version += str(telnet.before.decode('utf-8'))
                if m == 1:
                    telnet.sendline(' ')
                else:
                    break
        except pexpect.exceptions.TIMEOUT:
            lprint("    Время ожидания превышено! (timeout)")
            return 'Exception: TIMEOUT'
        except pexpect.exceptions.EOF:
            lprint("    Exception: EOF")
            return 'Exception: EOF'

        # -----------------------------------------HUAWEI--------------------------------------------------------------
        if bool(findall(r'Unrecognized command', version)):
            try:
                if match == 1:
                    telnet.sendline("sys")
                    if telnet.expect([']', 'Unrecognized command']):
                        telnet.sendline('super')
                        lprint(f'    <{device}>super')
                        telnet.expect('[Pp]ass')
                        telnet.sendline('sevaccess')
                        telnet.expect('>')
                        telnet.sendline('sys')
                        telnet.expect(']')
                    lprint(f'    <{device}>system-view')
                interface = interface_normal_view(interface)
                telnet.sendline(f"int {interface}")
                lprint(f"    [{device}]interface {interface}")
                telnet.expect(f']')
                # -------------------Huawei - ADMIN DOWN-------------------
                if status == 'down':
                    # 3 попытки положить интерфейс
                    while try_to_down > 0:
                        telnet.sendline('sh')
                        lprint(f'    [{device}-{interface}]shutdown')
                        telnet.expect(']')
                        # проверяем статуст порта
                        telnet.sendline(f'display current-configuration interface {interface}')
                        lprint('    Проверяем статус порта')
                        output = ''
                        while True:
                            match = telnet.expect([']', "  ---- More ----", pexpect.TIMEOUT])
                            output += str(telnet.before.decode('utf-8')).replace("[42D", '').strip()
                            if match == 1:
                                telnet.send(" ")
                                output += '\n'
                            else:
                                break
                        lprint(f'\n----------------------------------'
                               f'\n{output}'
                               f'\n----------------------------------')
                        if 'interface' in output and 'shutdown' in output:
                            lprint(f'    Порт {interface} admin down!')
                            break
                        elif 'interface' not in output:
                            lprint('    Не удалось определить статус порта')
                            telnet.sendline('sh')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            lprint('    QUIT!')
                            return 'cant status'
                        try_to_down -= 1
                        lprint(f'    Порт не удалось закрыть порт, пытаемся заново (осталось {try_to_down} попыток)')
                    else:
                        lprint(f'    Порт не закрыт! Не удалось установить порт в состояние admin down')
                        return 'cant set down'

                # --------------------Huawei - ADMIN UP---------------------
                elif status == 'up':
                    # 3 попытки поднять интерфейс
                    while try_to_up > 0:
                        telnet.sendline('undo sh')
                        lprint(f'    [{device}-{interface}]undo shutdown')
                        telnet.expect(']')
                        # проверяем статуст порта
                        telnet.sendline(f'display current-configuration int {interface}')
                        lprint('    Проверяем статус порта')
                        output = ''
                        while True:
                            match = telnet.expect([']', "  ---- More ----", pexpect.TIMEOUT])
                            output += str(telnet.before.decode('utf-8')).replace("[42D", '').strip()
                            if match == 1:
                                telnet.send(" ")
                                output += '\n'
                            else:
                                break
                        lprint(f'\n----------------------------------'
                               f'\n{output}'
                               f'\n----------------------------------')
                        if 'interface' in output and 'shutdown' not in output:    # не в down
                            lprint(f'    Порт {interface} admin up!')
                            break
                        elif 'interface' not in output:
                            lprint('    Не удалось определить статус порта')
                            telnet.sendline('sh')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            telnet.expect(']')
                            telnet.sendline('quit')
                            lprint('    QUIT!')
                            return 'cant status'
                        try_to_up -= 1
                        lprint(f'    Порт не удалось открыть порт, пытаемся заново (осталось {try_to_up} попыток)')
                    else:
                        lprint(f'    Порт не открыт! Не удалось установить порт в состояние admin up')
                        return 'cant set up'
            except Exception as e:
                lprint(f"    Exeption: {e}")
                return 'Exception: cant set port status'
            # ----------------------Huawei - SAVE------------------------
            try:
                telnet.sendline('quit')
                telnet.expect(']')
                telnet.sendline('quit')
                telnet.expect('>')
                # 3 попытки сохранить
                while try_to_save > 0:
                    telnet.sendline('save')
                    lprint(f'    <{device}>save')
                    telnet.expect('[Y/N]')
                    telnet.sendline('Y')
                    telnet.sendline('\n')
                    if not telnet.expect([' successfully', '>']):
                        lprint('    configuration saved!')
                        telnet.sendline('quit')
                        lprint('    QUIT\n')
                        return 'DONE'
                    else:
                        lprint(f'    Не удалось сохранить! пробуем заново (осталось {try_to_save} попыток')
                    try_to_save -= 1

                telnet.sendline('quit')
                lprint('    QUIT\n')
                return 'DONT SAVE'
            except Exception as e:
                lprint(f"    Exception: Don't saved! \nError: {e}")
                return 'Exception: DONT SAVE'

        # --------------------------------------CISCO - ELTEX----------------------------------------------------------
        elif bool(findall(r'Cisco IOS', version)) or bool(findall(r'Active-image: ', version)):
            try:
                if match == 1:
                    telnet.sendline("enable")
                    lprint(f'    {device}>enable')
                    telnet.expect('[Pp]assword')
                    telnet.sendline('sevaccess')
                    telnet.expect('#$')
                telnet.sendline('conf t')
                telnet.expect('#$')
                interface = interface_normal_view(interface)
                telnet.sendline(f"int {interface}")
                lprint(f"    {device}(config)#interface {interface}")
                telnet.expect('#$')
                # -------------------Cisco, Eltex - ADMIN DOWN--------------------------
                if status == 'down':
                    # 3 попытки положить интерфейс
                    while try_to_down > 0:
                        telnet.sendline('shutdown')   # закрываем порт
                        lprint(f'    {device}(config-if)#shutdown')
                        telnet.expect('#$')
                        # проверяем статуст порта
                        telnet.sendline(f'do show running-config int {interface}')
                        lprint('    Проверяем статус порта')
                        if try_to_down == 3 and bool(findall(r'Cisco IOS', version)):
                            telnet.expect('#$')
                        output = ''
                        while True:
                            match = telnet.expect(['#$', "--More--|More: <space>", pexpect.TIMEOUT])
                            output += str(telnet.before.decode('utf-8')).strip()
                            if match == 1:
                                telnet.send(" ")
                                output += '\n'
                            else:
                                break
                        lprint(f'\n----------------------------------'
                               f'\n{output}'
                               f'\n----------------------------------')
                        if 'interface' in output and 'shutdown' in output:
                            lprint(f'    Порт {interface} admin down!')
                            break
                        elif 'interface' not in output:
                            lprint('    Не удалось определить статус порта')
                            telnet.sendline('no shutdown')
                            lprint(f'    {device}(config-if)#no shutdown')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            lprint('    EXIT')
                            return 'cant status'
                        try_to_down -= 1
                        lprint(f'    Порт не удалось закрыть порт, пытаемся заново (осталось {try_to_down} попыток)')
                    else:
                        lprint(f'    Порт не закрыт! Не удалось установить порт в состояние admin down')
                        telnet.sendline('exit')
                        telnet.expect('#$')
                        telnet.sendline('exit')
                        telnet.expect('#$')
                        telnet.sendline('exit')
                        lprint('    EXIT')
                        return 'cant set down'

                # ---------------------Cisco, Eltex - ADMIN UP----------------------------
                elif status == 'up':
                    # 3 попытки поднять интерфейс
                    while try_to_up > 0:
                        telnet.sendline('no shutdown')    # открываем порт
                        lprint(f'    {device}(config-if)#no shutdown')
                        telnet.expect('#$')
                        # проверяем статуст порта
                        telnet.sendline(f'do show running-config int {interface}')
                        lprint('    Проверяем статус порта')
                        if try_to_up == 3 and bool(findall(r'Cisco IOS', version)):
                            telnet.expect('#$')
                        output = ''
                        while True:
                            match = telnet.expect(['#$', "--More--|More: <space>", pexpect.TIMEOUT])
                            output += str(telnet.before.decode('utf-8')).strip()
                            if match == 1:
                                telnet.send(" ")
                                output += '\n'
                            else:
                                break
                        lprint(f'\n----------------------------------'
                               f'\n{output}'
                               f'\n----------------------------------')
                        if 'interface' in output and 'shutdown' not in output:
                            lprint(f'    Порт {interface} admin up!')
                            break
                        elif 'interface' not in output:
                            lprint('    Не удалось определить статус порта\n')
                            telnet.sendline('shutdown')
                            lprint(f'    {device}(config-if)#shutdown')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            telnet.expect('#$')
                            telnet.sendline('exit')
                            lprint('    EXIT')
                            return 'cant status'
                        try_to_up -= 1
                        lprint(f'    Порт не удалось открыть порт, пытаемся заново (осталось {try_to_up} попыток)')
                    else:
                        lprint(f'    Порт не закрыт! Не удалось установить порт в состояние admin down')
                        telnet.sendline('exit')
                        telnet.expect('#$')
                        telnet.sendline('exit')
                        telnet.expect('#$')
                        telnet.sendline('exit')
                        lprint('    EXIT')
                        return 'cant set down'
            except Exception as e:
                lprint(f"    Exeption: {e}")
                return 'Exception: cant set port status'
            # ---------------------------Cisco, Eltex - SAVE------------------------------
            try:
                # telnet.expect('#')
                telnet.sendline('exit')
                lprint(f"    {device}(config-if)#exit")
                telnet.expect('#$')
                telnet.sendline('exit')
                lprint(f"    {device}(config)#exit")
                telnet.expect('#$')
                # 3 попытки сохранить
                # Если Cisco
                if bool(findall(r'Cisco IOS', version)):
                    while try_to_save > 0:
                        telnet.sendline('write')
                        lprint(f"    {device}#write")
                        telnet.expect('Building')
                        if telnet.expect(['OK', '#$']) == 0:
                            lprint("    Saved!")
                            telnet.sendline('exit')
                            lprint('    QUIT\n')
                            return 'DONE'
                        else:
                            try_to_save -= 1
                            lprint(f'    Не удалось сохранить! пробуем заново (осталось {try_to_save} попыток)')
                    telnet.sendline('exit')
                    lprint('    QUIT\n')
                    return 'DONT SAVE'
                # Если Eltex
                if bool(findall(r'Active-image: ', version)):
                    while try_to_save > 0:
                        telnet.sendline('write')
                        lprint(f"    {device}#write")
                        telnet.expect('Overwrite file')
                        telnet.sendline('Y')
                        telnet.expect('Y')
                        if telnet.expect(['succeeded', '#$']) == 0:
                            lprint("    Saved!")
                            telnet.sendline('exit')
                            lprint('    QUIT\n')
                            return 'DONE'
                        else:
                            try_to_save -= 1
                            lprint(f'    Не удалось сохранить! пробуем заново (осталось {try_to_save} попыток)')
                    telnet.sendline('exit')
                    lprint('    QUIT\n')
                    return 'DONT SAVE'
            except Exception as e:
                lprint(f"    Exception: Don't saved! \nError: {e}")
                return 'Exception: DONT SAVE'

        # ------------------------------------------D-LINK-------------------------------------------------------------
        elif bool(findall(r'Next possible completions:', version)):
            try:
                telnet.sendline('enable admin')
                if not telnet.expect(["[Pp]ass", "You already have the admin"]):
                    telnet.sendline('sevaccess')
                    telnet.expect('#')
                interface = interface_normal_view(interface)
                # -------------------------D-Link - ADMIN DOWN----------------------------
                if status == 'down':
                    # 3 попытки закрыть порт
                    while try_to_down > 0:
                        telnet.sendline(f'config ports {interface} medium_type fiber state disable')
                        lprint(f'    {device}#config ports {interface} medium_type fiber state disable')
                        telnet.sendline(f'config ports {interface} medium_type copper state disable')
                        lprint(f'    {device}#config ports {interface} medium_type copper state disable')
                        telnet.expect('#')
                        telnet.sendline('disable clipaging')
                        telnet.expect('#')
                        telnet.sendline("show ports des")
                        lprint('    Проверяем статус порта')
                        lprint(f'    {device}#show ports description')
                        telnet.expect('#')
                        telnet.sendline('\n')
                        telnet.expect('#')
                        output = telnet.before.decode('utf-8')
                        with open(f'{root_dir}/templates/int_des_d-link.template', 'r') as template_file:
                            int_des_ = textfsm.TextFSM(template_file)
                            result = int_des_.ParseText(output)  # интерфейсы
                        # Если не нашли интерфейсы или не нашли у необходимого интерфейса статуса, либо его самого
                        if not result or not [x[1] for x in result if interface_normal_view(x[0]) == interface]:
                            lprint('    Не удалось определить статус порта')
                            # возвращаем порт в прежнее состояние
                            telnet.sendline(f'config ports {interface} medium_type fiber state enable')
                            lprint(f'    {device}#config ports {interface} medium_type fiber state enable')
                            telnet.sendline(f'config ports {interface} medium_type copper state enable')
                            lprint(f'    {device}#config ports {interface} medium_type copper state enable')
                            telnet.expect('#')
                            telnet.sendline('logout')
                            lprint('    LOGOUT!')
                            return 'cant status'
                        # Проходимся по всем интерфейсам
                        for line in result:
                            # Если нашли требуемый порт и он Disabled (admin down)
                            if interface_normal_view(line[0]) == interface and line[1] == 'Disabled':
                                lprint(f'    Порт {interface} admin down!')
                                break
                        # Если требуемый порт НЕ Enabled
                        else:
                            try_to_down -= 1
                            lprint(f'    Порт не удалось закрыть, пытаемся заново (осталось {try_to_down} попыток)')
                            continue

                        break  # Если нашли требуемый порт и он Enabled
                    else:
                        lprint(f'    Порт не закрыт! Не удалось установить порт в состояние admin down')
                        telnet.sendline('logout')
                        lprint('    LOGOUT!')
                        return 'cant set down'
                # -------------------------D-Link - ADMIN UP------------------------------
                elif status == 'up':
                    # 3 попытки открыть порт
                    while try_to_up > 0:
                        telnet.sendline(f'config ports {interface} medium_type fiber state enable')
                        lprint(f'    {device}#config ports {interface} medium_type fiber state enable')
                        telnet.sendline(f'config ports {interface} medium_type copper state enable')
                        lprint(f'    {device}#config ports {interface} medium_type copper state enable')
                        telnet.expect('#')
                        telnet.sendline('disable clipaging')
                        telnet.expect('#')
                        lprint('    Проверяем статус порта')
                        telnet.sendline("show ports des")
                        lprint(f'    {device}#show ports description')
                        telnet.expect('#')
                        telnet.sendline('\n')
                        telnet.expect('#')
                        output = telnet.before.decode('utf-8')
                        with open(f'{root_dir}/templates/int_des_d-link.template', 'r') as template_file:
                            int_des_ = textfsm.TextFSM(template_file)
                            result = int_des_.ParseText(output)     # интерфейсы
                        # Если не нашли интерфейсы или не нашли у необходимого интерфейса статуса, либо его самого
                        if not result or not [x[1] for x in result if interface_normal_view(x[0]) == interface]:
                            lprint('    Не удалось определить статус порта')
                            # возвращаем порт в прежнее состояние
                            telnet.sendline(f'config ports {interface} medium_type fiber state disable')
                            lprint(f'    {device}#config ports {interface} medium_type fiber state disable')
                            telnet.sendline(f'config ports {interface} medium_type copper state disable')
                            lprint(f'    {device}#config ports {interface} medium_type copper state disable')
                            telnet.expect('#$')
                            telnet.sendline('logout')
                            lprint('    LOGOUT!')
                            return 'cant status'
                        # Проходимся по всем интерфейсам
                        for line in result:
                            # Если нашли требуемый порт и он Enabled (admin up)
                            if interface_normal_view(line[0]) == interface and line[1] == 'Enabled':
                                lprint(f'    Порт {interface} admin up!')
                                break
                        # Если требуемый порт НЕ Enabled
                        else:
                            try_to_up -= 1
                            lprint(f'    Порт не удалось открыть, пытаемся заново (осталось {try_to_up} попыток)')
                            continue

                        break   # Если нашли требуемый порт и он Enabled
                    else:
                        lprint(f'    Порт не закрыт! Не удалось установить порт в состояние admin up')
                        telnet.sendline('logout')
                        lprint('    LOGOUT!')
                        return 'cant set up'
            except Exception as e:
                lprint(f"    Exсeption: {e}")
                return 'Exception: cant set port status'
            # -------------------------D-Link - SAVE----------------------------------
            try:
                while try_to_save > 0:
                    telnet.sendline('save')
                    lprint(f'    {device}#save')
                    telnet.expect('Command: save')
                    m = telnet.expect(['[Ss]uccess|Done', '#'])
                    if m == 0:
                        lprint("    Saved!")
                        telnet.sendline('logout')
                        lprint('    LOGOUT!\n')
                        return 'DONE'
                    else:
                        try_to_save -= 1
                        lprint(f'    Не удалось сохранить! пробуем заново (осталось {try_to_save} попыток)')
                else:
                    lprint("    Don't saved!")
                    telnet.sendline('logout')
                    lprint('    LOGOUT!\n')
                    return 'DONT SAVE'
            except Exception as e:
                lprint(f"    Don't saved! \nError: {e}")
                return 'Exception: DONT SAVE'

        # -------------------------------------Alcatel - Linksys-------------------------------------------------------
        elif bool(findall(r'SW version', version)):
            try:
                telnet.sendline('conf')
                lprint(f'    {device}# configure')
                telnet.expect('# ')
                telnet.sendline(f'interface ethernet {interface}')
                lprint(f'    {device}(config)# interface ethernet {interface}')
                telnet.expect('# ')
                # ------------------Alcatel, Linksys - ADMIN DOWN---------------------
                if status == 'down':
                    while try_to_down > 0:
                        telnet.sendline('sh')
                        lprint(f'    {device}(config-if)# shutdown')
                        telnet.expect('# ')
                        telnet.sendline('do show interfaces configuration')
                        lprint('    Проверяем статус порта')
                        telnet.expect('Port')
                        port_state = ''
                        while True:
                            match = telnet.expect(['More: <space>', '# ', pexpect.TIMEOUT])
                            port_state += str(telnet.before.decode('utf-8')).strip()
                            if match == 0:
                                telnet.sendline(' ')
                            else:
                                break
                        with open(f'{root_dir}/templates/int_des_alcatel_linksys.template', 'r') as template_file:
                            int_des_ = textfsm.TextFSM(template_file)
                            result = int_des_.ParseText(port_state)  # Ищем интерфейсы
                        # Если не нашли интерфейсы или не нашли у необходимого интерфейса статуса, либо его самого
                        if not result or not [x[1] for x in result if x[0] == interface]:
                            lprint('    Не удалось определить статус порта')
                            # возвращаем порт в прежнее состояние
                            lprint('    Возвращаем порт в прежнее состояние')
                            telnet.sendline('no sh')
                            lprint(f'    {device}(config-if)# no shutdown')
                            telnet.sendline('exit')
                            telnet.sendline('exit')
                            telnet.sendline('exit')
                            lprint('    EXIT!')
                            return 'cant status'
                        # Проходимся по всем интерфейсам
                        for line in result:
                            # Если нашли требуемый порт и он admin down
                            if line[0] == interface and line[1] == 'Down':
                                lprint(f'    Порт {interface} admin down!')
                                break
                        # Если требуемый порт НЕ admin down
                        else:
                            try_to_down -= 1
                            lprint(f'    Порт не удалось закрыть, пытаемся заново (осталось {try_to_down} попыток)')
                            continue

                        break  # Если нашли требуемый порт и он admin down
                    else:
                        lprint(f'    Порт не закрыт! Не удалось установить порт в состояние admin down')
                        telnet.sendline('exit')
                        telnet.sendline('exit')
                        telnet.sendline('exit')
                        lprint('    EXIT!')
                        return 'cant set down'
                # ------------------Alcatel, Linksys - ADMIN UP-----------------------
                elif status == 'up':
                    while try_to_up > 0:
                        telnet.sendline('no sh')
                        lprint(f'    {device}(config-if)# no shutdown')
                        telnet.expect('# ')
                        telnet.sendline('do show interfaces configuration')
                        lprint('    Проверяем статус порта')
                        telnet.expect('Port')
                        port_state = ''
                        while True:
                            match = telnet.expect(['More: <space>', '# ', pexpect.TIMEOUT])
                            port_state += str(telnet.before.decode('utf-8')).strip()
                            if match == 0:
                                telnet.sendline(' ')
                            else:
                                break
                        with open(f'{root_dir}/templates/int_des_alcatel_linksys.template', 'r') as template_file:
                            int_des_ = textfsm.TextFSM(template_file)
                            result = int_des_.ParseText(port_state)  # Ищем интерфейсы
                        # Если не нашли интерфейсы или не нашли у необходимого интерфейса статуса, либо его самого
                        if not result or not [x[1] for x in result if x[0] == interface]:
                            lprint('    Не удалось определить статус порта')
                            # возвращаем порт в прежнее состояние
                            lprint('    Возвращаем порт в прежнее состояние')
                            telnet.sendline('sh')
                            lprint(f'    {device}(config-if)# shutdown')
                            telnet.sendline('exit')
                            telnet.sendline('exit')
                            telnet.sendline('exit')
                            lprint('    EXIT!')
                            return 'cant status'
                        # Проходимся по всем интерфейсам
                        for line in result:
                            # Если нашли требуемый порт и он admin up
                            if line[0] == interface and line[1] == 'Up':
                                lprint(f'    Порт {interface} admin up!')
                                break
                        # Если требуемый порт НЕ admin up
                        else:
                            try_to_up -= 1
                            lprint(f'    Порт не удалось открыть, пытаемся заново (осталось {try_to_up} попыток)')
                            continue

                        break  # Если нашли требуемый порт и он admin down
                    else:
                        lprint(f'    Порт не открыт! Не удалось установить порт в состояние admin up')
                        telnet.sendline('exit')
                        telnet.sendline('exit')
                        telnet.sendline('exit')
                        lprint('    EXIT!')
                        return 'cant set up'
            except Exception as e:
                lprint(f"    Exeption: {e}")
                return 'Exception: cant set port status'
            # ------------------------Alcatel, Linksys - SAVE-------------------------
            try:
                telnet.sendline('exit')
                telnet.expect('# ')
                telnet.sendline('exit')
                telnet.expect('# ')
                telnet.sendline('write')
                lprint(f'    {device}# write')
                telnet.expect('write')
                m = telnet.expect(['Unrecognized command', 'succeeded', '# '])
                if m == 0:
                    telnet.sendline('copy running-config startup-config')
                    lprint(f'    {device}# copy running-config startup-config')
                    telnet.expect('Overwrite file')
                    telnet.sendline('Yes')
                    m = telnet.expect(['!@#', 'succeeded', '# '])
                if m == 1:
                    lprint("    Saved!")
                    telnet.sendline('exit')
                    lprint('    EXIT!\n')
                    return 'DONE'
                else:
                    lprint('    Dont saved!')
                    telnet.sendline('exit')
                    lprint('    EXIT!\n')
                    return 'DONT SAVE'
            except Exception as e:
                lprint(f"    Don't saved! \nError: {e}")
                return 'Exception: DONT SAVE'

        # Edge-Core
        elif bool(findall(r'Hardware version', version)):
            lprint("    Edge-Core")

        # Zyxel
        elif bool(findall(r'ZyNOS', version)):
            lprint("    Zyxel")

        # ZTE
        elif bool(findall(r' ZTE Corporation:', version)):
            lprint("    ZTE")

        # Если не был определен вендор, то возвращаем False
        telnet.sendline('exit')
        return False


def find_port_by_desc(ring: dict, main_name: str, target_name: str):
    """
    Поиск интерфейса с description имеющим в себе имя другого оборудования \n
    :param ring:        Кольцо
    :param main_name:   Узел сети, где ищем
    :param target_name: Узел сети, который ищем
    :return:            Интерфейс
    """
    lprint("---- def find_port_by_desc ----")
    result = interfaces(ring, main_name)
    for line in result:
        if bool(findall(target_name, line[2])):  # Ищем строку, где в description содержится "target_name"
            return line[0]    # Интерфейс


def ping_from_device(device: str, ring: dict):
    """
    Заходим на оборудование через telnet и устанавливаем состояние конкретного порта
    :param ring"    Кольцо
    :param device:          Имя узла сети, с которым необходимо взаимодействовать
    :return:                В случае успеха возвращает 1, неудачи - 0
    """
    with pexpect.spawn(f"telnet {ring[device]['ip']}") as telnet:
        try:
            if telnet.expect(["[Uu]ser", 'Unable to connect']):
                lprint("    Telnet недоступен!")
                return False
            telnet.sendline(ring[device]["user"])
            lprint(f"    Login to {device}")
            telnet.expect("[Pp]ass")
            telnet.sendline(ring[device]["pass"])
            lprint(f"    Pass to {device}")
            match = telnet.expect([']', '>', '#', 'Failed to send authen-req'])
            if match == 3:
                lprint('    Неверный логин или пароль!')
                return False
            telnet.sendline('show version')
            version = ''
            while True:
                m = telnet.expect([']', '-More-', '>', '#'])
                version += str(telnet.before.decode('utf-8'))
                if m == 1:
                    telnet.sendline(' ')
                else:
                    break

            devices_status = [(device, True)]
            lprint(f'Доступно   {device}')
            try:
                telnet.sendline(f'ping {ring[device]["ip"]}')
                telnet.sendcontrol('c')
                telnet.expect([']', '>', '#'])
            except pexpect.exceptions.TIMEOUT:
                telnet.sendcontrol('c')
                telnet.expect([']', '>', '#'])
            for dev in ring:
                if device != dev:
                    try:
                        telnet.sendline(f'ping {ring[dev]["ip"]}')

                        # Huawei
                        if bool(findall(r'Error: Unrecognized command', version)):
                            match = telnet.expect(['Request time out', 'Error', 'Reply from'])
                        # Cisco
                        elif bool(findall(r'Cisco IOS', version)):
                            match = telnet.expect(['is 0 percent', 'Unrecognized host', 'is 100 percent'])
                        # D-Link
                        elif bool(findall(r'Next possible completions:', version)):
                            match = telnet.expect(['Request timed out', 'Command: ping', 'Reply from'])
                        # Alcatel, Linksys
                        elif bool(findall(r'SW version', version)):
                            match = telnet.expect([' 0 packets received', 'Host not found', 'min/avg/max'])
                        # Eltex
                        elif bool(findall(r'Active-image: ', version)):
                            match = telnet.expect(['PING: timeout', 'Host not found', 'bytes from'])
                        # Если не был определен вендор, то возвращаем False
                        else:
                            telnet.sendline('exit')
                            return False

                        if match < 2:
                            telnet.sendcontrol('c')
                            devices_status.append((dev, False))
                            lprint(f'Недоступно {dev}')
                        elif match == 2:
                            telnet.sendcontrol('c')
                            devices_status.append((dev, True))
                            lprint(f'Доступно   {dev}')
                        telnet.expect([']', '>', '#'])
                    except pexpect.exceptions.TIMEOUT:
                        devices_status.append((dev, False))
                        lprint(f'Недоступно {dev} Exception: timeout')
                        telnet.sendcontrol('c')
                        telnet.expect([']', '>', '#'])

            # Huawei
            if bool(findall(r'Error: Unrecognized command', version)):
                telnet.sendline('quit')
            # Cisco
            elif bool(findall(r'Cisco IOS', version)):
                telnet.sendline('exit')
            # D-Link
            elif bool(findall(r'Next possible completions:', version)):
                telnet.sendline('logout')
            # Alcatel, Linksys
            elif bool(findall(r'SW version', version)):
                telnet.sendline('exit')
            # Eltex
            elif bool(findall(r'Active-image: ', version)):
                telnet.sendline('exit')

            return devices_status           # Возвращаем список

        except pexpect.exceptions.TIMEOUT:
            lprint("    Время ожидания превышено! (timeout)")
            return False


def ping_devices(ring: dict):
    """
    Функция определяет, какие из узлов сети в кольце доступны по "ping" \n
    :param ring: Кольцо
    :return: Двумерный список: имя узла и его статус "True" - ping успешен, "False" - нет
    """
    status = []
    lprint("---- Пингуем все узлы сети ----")

    def ping(ip, device):
        result = subprocess.run(['ping', '-c', '3', '-n', ip], stdout=subprocess.DEVNULL)
        if not result.returncode:  # Проверка на доступность: 0 - доступен, 1 и 2 - недоступен
            status.append((device, True))
            lprint(f"    ✅ {device}")
        else:
            status.append((device, False))
            lprint(f"    ❌ {device}")

    with ThreadPoolExecutor(max_workers=10) as executor:    # Многопоточность
        for device in ring:
            executor.submit(ping, ring[device]['ip'], device)   # Запускаем фунцию ping и передаем ей переменные

    return status
