#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pexpect
import yaml
from pprint import pprint
import re
from re import findall
import textfsm
from tabulate import tabulate

dev = 'SVSL-01-MotR-ASW1'
# ip = "10.29.4.203"


def search_admin_down(ip, login, password):
    int_des_full = huawei_telnet_int_des(ip, login, password)



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
        output = re.sub("\n +\n", "\n", output)
        return output


with open('rings.yaml') as rings_yaml:
    rings = yaml.safe_load(rings_yaml)
    for ring in rings:

        for device in rings[ring]:

            if device == dev:
                current_ring = rings[ring]
                break

            # for item in rings[ring][device]:
            #     print(rings[ring][device][item])
pprint(current_ring)
print(current_ring[dev]["ip"])

# Поиск ADMIN DOWN
with open("templates/int_des_huawei.template", 'r') as templ, open("output") as output:
    int_des_ = textfsm.TextFSM(templ)
    header = int_des_.header
    result = int_des_.ParseText(output.read())
    if result:
        for position, elem in enumerate(current_ring):
            for res_line in result:
                if bool(findall(elem, res_line[3])):
                    print("GOT")
                    print(current_ring[position])
    pprint(result)
    print(tabulate(result, headers=header))

# for elem in current_ring:
#     if current_ring[elem]["vendor"] == "huawei":
#         int_des = huawei_telnet_int_des(current_ring[elem]["ip"],
#                                         current_ring[elem]["user"],
#                                         current_ring[elem]["pass"])
#         with open('output', 'a+') as file:
#             file.write(int_des)
#             print(int_des)

