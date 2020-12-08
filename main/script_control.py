#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from sys import argv
from re import sub


def set_script_global_variables(variable: str, status: str):
    with open(f'{root_dir}/config.conf', 'r') as global_variables_file:
        global_variables = global_variables_file.read()  # считываем файл конфигурации
    with open(f'{root_dir}/config.conf', 'w') as global_variables_file:
        # Перезаписываем переменную по фильтру
        global_variables_file.write(sub(f'{variable} = \S+', f'{variable} = {status}', global_variables))
        print(f'{variable} = {status}')


if __name__ == '__main__':
    root_dir = os.path.split(os.path.join(os.getcwd(), os.path.split(argv[0])[0]))[0]

    if len(argv) > 2:
        set_script_global_variables(argv[1], argv[2])
