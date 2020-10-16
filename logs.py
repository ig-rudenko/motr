from datetime import datetime, date
import os
import sys


def lprint(text: str):
    print(text)
    today = date.today().strftime("%d-%m-%Y")
    root_dir = os.path.join(os.getcwd(), os.path.split(sys.argv[0])[0])
    if not os.path.exists(f'{root_dir}/logs/{today}.log'):
        with open(f'{root_dir}/logs/{today}.log', 'w') as _:
            pass
    with open(f'{root_dir}/logs/{today}.log', 'a') as log_file:
        log_file.write(f'[{datetime.now().strftime("%H:%m:%S")}] {text}\n')


if __name__ == '__main__':
    lprint('    hello world')
    lprint('----------------')
    lprint('    done!')
