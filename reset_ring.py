#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import motr
import yaml
import sys
import os
from datetime import datetime

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])

if __name__ == '__main__':

    if len(sys.argv) == 1:
        print("Не указано имя узла сети!")
        sys.exit()
    dev = sys.argv[1]
    current_ring, current_ring_list, current_ring_name = motr.find_ring_by_device(dev)

    # Заголовок
    print('\n')
    print('-' * 20 + 'NEW SESSION' + '-' * 20)
    print(' ' * 12 + str(datetime.now()))
    print(' ' * ((51 - len(dev)) // 2) + dev + ' ' * ((51 - len(dev)) // 2))
    print('-' * 51)

    with open(f'{root_dir}/rotated_rings.yaml') as rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
        for ring in rotated_rings:
            if current_ring_name == ring:           # Найдено
                print("GOT RING: "+ring)
                break
        else:
            print('Кольцо не находится в списке колец требуемых к развороту "по умолчанию"')
            sys.exit()      # Выход

    devices_ping = motr.ring_ping_status(current_ring)

    for device_name, device_status in devices_ping:
        if not device_status:
            print("Не все узлы сети в кольце восстановлены, дальнейший разворот прерван!")
            break
    else:   # Когда все узлы сети в кольце доступны, то...
        print("ALL DEVICES AVAILABLE!\n")
        print(f'Закрываем порт {rotated_rings[current_ring_name]["default_port"]} '
              f'на {rotated_rings[current_ring_name]["default_host"]}')
        if motr.set_port_status(current_ring,
                                rotated_rings[current_ring_name]["default_host"],
                                rotated_rings[current_ring_name]["default_port"], "down"):

            print(f'Поднимаем порт {rotated_rings[current_ring_name]["admin_down_port"]} '
                  f'на {rotated_rings[current_ring_name]["admin_down_host"]}')
            if motr.set_port_status(current_ring,
                                    rotated_rings[current_ring_name]["admin_down_host"],
                                    rotated_rings[current_ring_name]["admin_down_port"], "up"):
                print(f"Кольцо развернуто!\n"
                      f"На узле сети {rotated_rings[current_ring_name]['default_host']} порт "
                      f"{rotated_rings[current_ring_name]['default_port']} в статусе admin down")
                motr.delete_ring_from_deploying_list(current_ring_name) # Удаляем кольцо из списка требуемых к развороту

            else:   # Если не удалось поднять порт на оборудовании с admin_down, то...
                # ...поднимаем порт, который положили на предыдущем шаге
                motr.set_port_status(current_ring,
                                     rotated_rings[current_ring_name]["default_host"],
                                     rotated_rings[current_ring_name]["default_port"], "up")
                print(f'Не удалось поднять порт на оборудовании: {rotated_rings[current_ring_name]["admin_down_host"]}!'
                      f'\nРазворот кольца остался прежним')
        else:
            print(f'Не удалось закрыть порт на оборудовании: {rotated_rings[current_ring_name]["default_host"]}!'
                  f'\nРазворот кольца остался прежним')

