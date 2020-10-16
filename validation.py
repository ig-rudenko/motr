import yaml
from re import findall
import email_notifications as email
from motr import root_dir  # Импорт глобальной переменной
from logs import lprint
import os


def validation(files: list) -> bool:
    '''
    Проверяет структуру файлов колец и возвращает True, когда все файлы прошли проверку и
    False, если хотя бы в одном файле найдено нарушение структуры \n
    :param files: список файлов
    :return: bool
    '''
    valid = [True for _ in range(len(files))]
    if not files:
        lprint(f'Укажите в файле конфигурации {root_dir} файл с кольцами или папку')
        return False
    invalid_files = ''
    text = ''
    for num, file in enumerate(files):
        validation_text = ''
        try:
            with open(f'{file}', 'r') as rings_yaml:  # Чтение файла
                try:
                    rings = yaml.safe_load(rings_yaml)  # Перевод из yaml в словарь
                    if rings:
                        for ring in rings:
                            for dev in rings[ring]:
                                if len(dev.split()) > 1:
                                    validation_text += f'{ring} --> Имя узла сети должно быть записано в одно слово: {dev}\n'
                                    valid[num] = False
                                try:
                                    if not rings[ring][dev]['user']:
                                        validation_text += f'{ring} --> {dev} | не указан user\n'
                                        valid[num] = False
                                    if len(str(rings[ring][dev]['user']).split()) > 1:
                                        validation_text += f'{ring} --> {dev} | '\
                                                            f'user должен быть записан в одно слово: '\
                                                            f'{rings[ring][dev]["user"]}\n'
                                        valid[num] = False
                                except:
                                    validation_text += f'{ring} --> {dev} | не указан user\n'
                                    valid[num] = False

                                try:
                                    if not rings[ring][dev]['pass']:
                                        validation_text += f'{ring} --> {dev} | не указан пароль\n'
                                        valid[num] = False
                                    if len(str(rings[ring][dev]['pass']).split()) > 1:
                                        validation_text += f'{ring} --> {dev} | '\
                                                            f'пароль должен быть записан в одно слово: '\
                                                            f'{rings[ring][dev]["pass"]}\n'
                                        valid[num] = False
                                except:
                                    validation_text += f'{ring} --> {dev} | не указан пароль\n'
                                    valid[num] = False

                                try:
                                    if not rings[ring][dev]['ip']:
                                        validation_text += f'{ring} --> {dev} | не указан IP\n'
                                        valid[num] = False
                                    elif not bool(findall('\d{1,4}(\.\d{1,4}){3}', rings[ring][dev]['ip'])):
                                        validation_text += f'{ring} --> {dev} | '\
                                                            f'IP указан неверно: '\
                                                            f'{rings[ring][dev]["ip"]}\n'
                                        valid[num] = False
                                except:
                                    validation_text += f'{ring} --> {dev} | не указан IP\n'
                                    valid[num] = False
                    else:
                        validation_text += f'Файл "{root_dir}/check.yaml" пуст!\n'
                        valid[num] = False
                except Exception as e:
                    validation_text += str(e)
                    validation_text += '\nОшибка в синтаксисе!\n'
                    valid[num] = False
        except Exception as e:
            validation_text += str(e)
            valid[num] = False
        if not valid[num]:
            invalid_files += f'{file}\n'
            text += f'\n{file}\n{validation_text}'

    validation_text = ''
    valid_2 = True
    if not os.path.exists(f'{root_dir}/rotated_rings.yaml'):
        with open(f'{root_dir}/rotated_rings.yaml', 'w') as rr:
            rr.write("null: don't delete")
    try:
        with open(f'{root_dir}/rotated_rings.yaml', 'r') as rotated_rings_yaml:
            try:
                rotated_rings = yaml.safe_load(rotated_rings_yaml)
                if rotated_rings:
                    for ring in rotated_rings:
                        if not ring or rotated_rings[ring] == 'Deploying':
                            continue
                        try:
                            if not rotated_rings[ring]['admin_down_host']:
                                validation_text += f'{ring} --> не указан admin_down_host ' \
                                                   f'(узел сети, где порт в состоянии admin down)\n'
                                valid_2 = False
                            if len(str(rotated_rings[ring]['admin_down_host']).split()) > 1:
                                validation_text += f'{ring} --> admin_down_host должен быть записан в одно слово: '\
                                                    f'{rotated_rings[ring]["admin_down_host"]}\n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан admin_down_host ' \
                                               f'(узел сети, где порт в состоянии admin down)\n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['admin_down_port']:
                                validation_text += f'{ring} --> не указан admin_down_port ' \
                                                   f'(порт узла сети в состоянии admin down)/n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан admin_down_port ' \
                                               f'(порт узла сети в состоянии admin down)\n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['admin_down_to']:
                                validation_text += f'{ring} --> не указан admin_down_to '\
                                      f'(узел сети, который находится непосредственно за узлом,' \
                                                   f' у которого порт в состоянии admin down)\n'
                                valid_2 = False
                            if len(str(rotated_rings[ring]['admin_down_to']).split()) > 1:
                                validation_text += f'{ring} --> admin_down_to должен быть записан в одно слово: '\
                                                    f'{rotated_rings[ring]["admin_down_to"]}\n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан admin_down_to '\
                                  f'(узел сети, который находится непосредственно за узлом,' \
                                               f' у которого порт в состоянии admin down)\n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['default_host']:
                                validation_text += f'{ring} --> не указан default_host '\
                                      f'(узел сети, который должен иметь статус порта admin down по умолчанию)/n'
                                valid_2 = False
                            if len(str(rotated_rings[ring]['default_host']).split()) > 1:
                                validation_text += f'{ring} --> default_host должен быть записан в одно слово: '\
                                                    f'{rotated_rings[ring]["default_host"]}/n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан default_host '\
                                  f'(узел сети, который должен иметь статус порта admin down по умолчанию)/n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['default_port']:
                                validation_text += f'{ring} --> не указан default_port '\
                                      f'(порт узла сети, который должен иметь статус порта admin down по умолчанию)\n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан default_port '\
                                  f'(порт узла сети, который должен иметь статус порта admin down по умолчанию)\n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['default_to']:
                                validation_text += f'{ring} --> не указан default_to '\
                                      f'(узел сети, который находится непосредственно за узлом сети, '\
                                      f'который должен иметь статус порта admin down по умолчанию)\n'
                                valid_2 = False
                            if len(str(rotated_rings[ring]['default_to']).split()) > 1:
                                validation_text += f'{ring} --> default_to должен быть записан в одно слово: '\
                                                    f'{rotated_rings[ring]["default_to"]}\n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан default_to '\
                                                f'(узел сети, который находится непосредственно за узлом сети, '\
                                                f'который должен иметь статус порта admin down по умолчанию)\n'
                            valid_2 = False

                        try:
                            if not rotated_rings[ring]['priority']:
                                validation_text += f'{ring} --> не указан priority '
                                valid_2 = False
                            if not isinstance(rotated_rings[ring]['priority'], int):
                                validation_text += f'{ring} --> priority должен быть целочисленным числом: '\
                                                    f'{rotated_rings[ring]["priority"]}\n'
                                valid_2 = False
                        except:
                            validation_text += f'{ring} --> не указан priority \n'
                            valid_2 = False
                else:
                    with open(f'{root_dir}/rotated_rings.yaml', 'w') as save_ring:
                        save = {None: "don't delete"}
                        yaml.dump(save, save_ring, default_flow_style=False)
                    valid_2 = False
            except Exception as e:
                validation_text += str(e)
                validation_text += '\nОшибка в синтаксисе!\n'
                valid_2 = False
    except Exception as e:
        validation_text += str(e)
        valid_2 = False
    if not valid_2:
        invalid_files += f'{root_dir}/rotated_rings.yaml\n'
        text += f'\n{root_dir}/rotated_rings.yaml\n{validation_text}'

    for v in valid:
        if not v or not valid_2:
            email.send_text('Разворот колец невозможен!',
                            f'Ошибка в структуре: \n'
                            f'{invalid_files}'
                            f'\n{text}')
            lprint(f'Ошибка в структуре: \n{invalid_files}\n{text}')
            return False
    return True
