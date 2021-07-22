import os
import sys
import configparser
from re import findall

# Работа с файлом конфигурации


def get_config(conf: str = None):
    """
    Переопределяет глобальные переменные считывая файл конфигурации "config.conf", если такового не существует,
    то создает с настройками по умолчанию \n
    :return: None
    """
    global email_notification
    global rings_files
    if not os.path.exists(f'{sys.path[0]}/config.conf'):
        set_default_config()
    config = configparser.ConfigParser()
    config.read(f'{sys.path[0]}/config.conf')
    motr_status = 'enable' if config.get("Settings", 'motr_status') == 'enable' else 'disable'
    email_notification = 'enable' if config.get("Settings", 'email_notification') == 'enable' else 'disable'
    tg_bot_notification = 'enable' if config.get("Settings", 'tg_bot_notification') == 'enable' else 'disable'
    rings_files = get_rings()

    if conf == 'rings_directory':
        return rings_files
    elif conf == 'email_notification':
        return email_notification
    elif conf == 'to_address':
        return config.get("Email", 'to_address')
    elif conf == 'tg_bot_notification':
        return tg_bot_notification
    elif conf == 'TG_bot_token':
        return config.get("TG_bot", 'token')
    elif conf == 'TG_bot_chat_id':
        return config.get("TG_bot", 'chat_id')
    elif conf == 'motr_status':
        return motr_status      # вкл/откл скрипта
    else:
        return None


def set_default_config() -> None:
    cfg = configparser.ConfigParser()
    cfg.add_section('Settings')
    cfg.set("Settings", 'motr_status', 'enable')
    cfg.set("Settings", 'email_notification', 'enable')
    cfg.set("Settings", 'tg_bot_notification', 'enable')
    cfg.set("Settings", 'rings_directory', '~rings/*')
    cfg.add_section('Email')
    cfg.set("Email", 'to_address', 'irudenko@sevtelecom.ru, '
                                   'syankovskiy@sevtelecom.ru, '
                                   'atemnyh@sevtelecom.ru,'
                                   ' jandreyanova@sevtelecom.ru, '
                                   'eshtyrbu@sevtelecom.ru, '
                                   'adoronenkov@sevtelecom.ru, '
                                   'epopova@sevtelecom.ru, '
                                   'vtihonova@sevtelecom.ru')
    cfg.add_section('TG_bot')
    cfg.set("TG_bot", 'token', '')
    cfg.set("TG_bot", 'chat_id', '')
    with open(f'{sys.path[0]}/config.conf', 'w') as cfg_file:
        cfg.write(cfg_file)


def return_files(path: str) -> list:
    """
    Возвращает все файлы в папке и подпапках \n
    :param path: Путь до папки
    :return:     Список файлов
    """
    files = os.listdir(path)
    rings_f = []
    for file in files:
        if os.path.isfile(os.path.join(path, file)):
            rings_f.append(os.path.join(path, file))
        elif os.path.isdir(os.path.join(path, file)):
            rings_f += return_files(os.path.join(path, file))
    return rings_f


def get_rings() -> list:
    """
    Из конфигурационного файла достаем переменную "rings_directory" и указываем все найденные файлы \n
    :return: Список файлов с кольцами
    """
    config = configparser.ConfigParser()
    config.read(f'{sys.path[0]}/config.conf')

    rings_directory = config.get("Settings", 'rings_directory').split(',')
    rings_files = []

    for elem in rings_directory:
        elem = elem.strip()
        elem = elem[:-2] if elem.endswith('/*') else elem
        elem = elem[:-1] if elem.endswith('/') else elem
        elem = os.path.join(sys.path[0], elem[1:]) if elem.startswith('~') else elem
        if bool(findall(r'\w\*$', elem)):
            root, head = os.path.split(elem)
            sub_files = os.listdir(root)
            for sub_elem in sub_files:
                if sub_elem.startswith(head[:-1]):
                    if os.path.isfile(os.path.join(root, sub_elem)):
                        rings_files.append(os.path.join(root, sub_elem))
                    elif os.path.isdir(os.path.join(root, sub_elem)):
                        rings_files += return_files(os.path.join(root, sub_elem))
        if os.path.isfile(elem):
            rings_files.append(elem)
        elif os.path.isdir(elem):
            rings_files += return_files(elem)
    return [i for i in set(rings_files)]
