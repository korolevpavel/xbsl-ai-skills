from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / 'fixtures/ui_deltas_10'
REFERENCE = ROOT / 'skills/xbsl-form-add/references/ui-deltas-10.md'


def test_form_ui_10_example_has_explicit_optional_properties() -> None:
    data = yaml.safe_load((FIXTURE / 'ФормаЗаказа.yaml').read_text(encoding='utf-8'))
    template = data['Наследует']['Содержимое']
    discussion = template['ОсновнойРаздел']['Содержимое'][0]
    module = (FIXTURE / 'ФормаЗаказа.xbsl').read_text(encoding='utf-8')

    assert template['Тип'] == 'ШаблонФормыСРазделами'
    assert template['ПриСменеГруппыРаздела'] == 'ПриСменеГруппыРаздела'
    assert discussion['Тип'] == 'КомпонентОбсуждения'
    assert discussion['ОтображатьЗаголовок'] == 'Ложь'
    assert 'СобытиеСДанными<Группа>' in module


def test_embedded_pages_nodes_belong_to_application_component() -> None:
    app = yaml.safe_load((FIXTURE / 'Приложение.yaml').read_text(encoding='utf-8'))
    form = yaml.safe_load((FIXTURE / 'ФормаЗаказа.yaml').read_text(encoding='utf-8'))
    inherited = app['Наследует']
    assert inherited['Тип'] == 'СтандартноеКлиентскоеПриложениеСРазделами'
    assert inherited['ВстроенныеВебСтраницы']['ВебСтраницы'][0]['Ид'] == 'ВнешняяСтраница'
    fragment = inherited['ИнтерфейсВстроенныхВебСтраниц']['КомандыПанели']
    assert fragment['Тип'] == 'ФрагментКомандногоИнтерфейса'
    assert fragment['Элементы'][0]['Тип'] == 'НавигационнаяКоманда'
    assert fragment['Элементы'][0]['ТипФормы'] == 'ФормаЗаказа'
    assert 'Имя' not in fragment['Элементы'][0]
    assert 'ВстроенныеВебСтраницы' not in form['Наследует']


def test_reference_guards_undocumented_menu_variants() -> None:
    text = REFERENCE.read_text(encoding='utf-8')
    assert 'КомпонентМеню' in text
    assert 'ОсновнаяКомандаМеню' in text
    assert 'без конкретного компонента или команды' in text
