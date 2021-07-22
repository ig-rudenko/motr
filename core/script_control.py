#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from re import sub


def set_script_global_variables(variable: str, status: str):
    with open(f'{sys.path[0]}/config.conf', 'r') as global_variables_file:
        global_variables = global_variables_file.read()  # считываем файл конфигурации
    with open(f'{sys.path[0]}/config.conf', 'w') as global_variables_file:
        # Перезаписываем переменную по фильтру
        global_variables_file.write(sub(f'{variable} = \S+', f'{variable} = {status}', global_variables))
        print(f'{variable} = {status}')


if __name__ == '__main__':
    if len(sys.argv) > 2:
        set_script_global_variables(sys.argv[1], sys.argv[2])
