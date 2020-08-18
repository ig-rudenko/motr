#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import motr
import yaml
import sys

dev = 'SVSL-01-MotR-ASW1'
# dev = sys.argv[1]

current_ring, current_ring_list, current_ring_name = motr.find_ring_by_device(dev)
with open('/home/irudenko/motr/rotated_rings.yaml') as rings_yaml:  # Чтение файла
    if rings_yaml.read():
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
    print("ALL DEVICES AVAILABLE!")
    if motr.set_port_status(current_ring, rotated_rings[current_ring_name]["default_host"],
                            rotated_rings[current_ring_name]["default_port"],
                            "down"):
        if motr.set_port_status(current_ring, rotated_rings[current_ring_name]["admin_down_host"],
                                rotated_rings[current_ring_name]["admin_down_port"],
                                "up"):
            print(f"Кольцо развернуто!\n"
                  f"На узле сети {rotated_rings[current_ring_name]['default_host']} порт"
                  f"{rotated_rings[current_ring_name]['default_port']} статус admin down")
            del rotated_rings[current_ring_name]    # Удаляем кольцо из списка требуемых к развороту
            with open('/home/irudenko/motr/rotated_rings.yaml', 'w') as save_ring:
                yaml.dump(rotated_rings, save_ring, default_flow_style=False)   # Переписываем файл

        else:   # Если не удалось поднять порт на оборудовании с admin_down, то...
            # ...поднимаем порт, который положили на предыдущем шаге
            motr.set_port_status(current_ring, rotated_rings[current_ring_name]["default_host"],
                                 rotated_rings[current_ring_name]["default_port"],
                                 "up")
            print(f'Не удалось поднять порт на оборудовании: {rotated_rings[current_ring_name]["admin_down_host"]}!'
                  f'Разворот кольца остался прежним')
