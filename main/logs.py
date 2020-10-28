
from datetime import datetime, date
import os
import sys

today = date.today().strftime("%d-%m-%Y")  # Дата на сегодня в формате ДД-ММ-ГГГГ
root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])  # Корневая директория
log_file_name = sys.argv[2] if len(sys.argv) >= 2 else 'unknown'  # Если не запущен с основного файла, то логи unknown


def check_logs_file():
    if not os.path.exists(f'{root_dir}/logs/{today}-reset'):    # Если нет папки с текущей датой, то...
        os.mkdir(f'{root_dir}/logs/{today}-reset')                  # ...создаем
    if not os.path.exists(f'{root_dir}/logs/{today}'):          # Если нет папки с текущей датой, то...
        os.mkdir(f'{root_dir}/logs/{today}')                        # ...создаем
    if not os.path.exists(f'{root_dir}/logs/{today}-reset/{log_file_name}.log'):    # Если нет файла логов, то...
        with open(f'{root_dir}/logs/{today}-reset/{log_file_name}.log', 'w') as _:      # ...создаем
            pass
    if not os.path.exists(f'{root_dir}/logs/{today}/{log_file_name}.log'):          # Если нет файла логов, то...
        with open(f'{root_dir}/logs/{today}/{log_file_name}.log', 'w') as _:            # ...создаем
            pass


def lprint(text: str):
    print(text)
    check_logs_file()
    with open(f'{root_dir}/logs/{today}/{log_file_name}.log', 'a') as log_file:  # Открываем файл логов
        log_file.write(f'[{datetime.now().strftime("%H:%M:%S")}] {text}\n')     # Запись


def lrprint(text: str):
    print(text)
    check_logs_file()
    with open(f'{root_dir}/logs/{today}-reset/{log_file_name}.log', 'a') as log_file:
        log_file.write(f'[{datetime.now().strftime("%H:%M:%S")}] {text}\n')


if __name__ == '__main__':
    lprint('    hello world')
    lprint('----------------')
    lprint('    done!')
