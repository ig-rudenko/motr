#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from main.config import get_config
from sys import argv


def check_options(option):
    option_status = get_config(option)
    if not option_status:
        return -1
    elif option_status == 'enable':
        return 1
    elif option_status == 'disable':
        return 0


if __name__ == '__main__':
    if len(argv) >= 2:
        print(check_options(argv[1]))
