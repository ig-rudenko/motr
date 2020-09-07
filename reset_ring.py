#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import motr
import yaml
import sys
import os
from datetime import datetime
import email_notifications as email

root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])
successor_name = ''
email_notification = 'enable'
rings_files = []

if __name__ == '__main__':

    if len(sys.argv) == 1:
        print("Не указано имя узла сети!")
        sys.exit()
    motr.get_config()
    if not motr.validation(rings_files):
        sys.exit()

    dev = sys.argv[1]
    current_ring, current_ring_list, current_ring_name = motr.get_ring(dev)

    # Заголовок
    print('\n')
    print('-' * 20 + 'NEW SESSION' + '-' * 20)
    print(' ' * 12 + str(datetime.now()))
    print(' ' * ((51 - len(dev)) // 2) + dev + ' ' * ((51 - len(dev)) // 2))
    print('-' * 51)

    with open(f'{root_dir}/rotated_rings.yaml') as rings_yaml:  # Чтение файла
        rotated_rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
        for ring in rotated_rings:
            if current_ring_name == ring and rotated_rings[ring] == 'Deploying':
                print("Кольцо в данный момент разворачивается!")
                sys.exit()
            elif current_ring_name == ring and rotated_rings[ring]['priority'] == 1:           # Найдено
                print("GOT RING: "+ring)
                break
        else:
            print('Кольцо не находится в списке колец требуемых к развороту "по умолчанию"')
            sys.exit()      # Выход

    devices_ping = motr.ping_devices(current_ring)

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
                print("Ожидаем 2мин (не прерывать!)")
                motr.time_sleep(120)  # Ожидаем 2мин на перестройку кольца
                new_ping_status = motr.ping_from_device(current_ring_list[0], current_ring)
                for _, available in new_ping_status:
                    if not available:
                        break
                else:
                    print("Все устройства в кольце после разворота доступны!\nОтправка e-mail")
                    # Отправка e-mail
                    if email_notification == 'enable':
                        email.send(current_ring_name, current_ring_list, devices_ping, new_ping_status,
                                   rotated_rings[current_ring_name]['default_host'],
                                   rotated_rings[current_ring_name]['default_port'],
                                   rotated_rings[current_ring_name]['default_to'],
                                   rotated_rings[current_ring_name]['admin_down_host'],
                                   rotated_rings[current_ring_name]['admin_down_port'],
                                   rotated_rings[current_ring_name]['admin_down_to'])

                    motr.delete_ring_from_deploying_list(current_ring_name) # Удаляем кольцо из списка требуемых к развороту
                    sys.exit()      # Завершение работы программы

                # Если в кольце есть недоступные устройства
                print("После разворота в положение \"по умолчанию\" появились недоступные узлы сети\n"
                      "Выполняем полную проверку заново!")
                motr.main(new_ping_status, current_ring, current_ring_list, current_ring_name)

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

