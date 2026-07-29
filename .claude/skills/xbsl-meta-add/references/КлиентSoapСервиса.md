# Спецификация: КлиентSoapСервиса

## Назначение

Platform facts:

- `ВидЭлемента: КлиентSoapСервиса` описывает клиента внешнего SOAP-сервиса.
- `UrlПоУмолчанию` задает URL вызова; другой URL передается через `КлиентHttp`
  в конструктор порожденного типа.
- `ВерсияSoap` принимает SOAP 1.1 или SOAP 1.2; default: SOAP 1.1.
- В проект необходимо добавить WSDL-описание сервиса. При загрузке из файла
  основное описание получает имя `<ИмяКлиентаSoapСервиса>.Wsdl.1`.
- Если WSDL ссылается на другие WSDL или XSD, эти ресурсы также добавляются в
  проект. Некорректные ссылки надо заменить на имена файлов проекта.
- На основе WSDL создается тип `{ИмяКлиентаSoapСервиса}` с методами операций,
  структурами параметров и структурой результата.

Local conventions:

- Minimal generation создает `<Имя>.yaml` и требует рядом WSDL-файл.
- XSD создавай только для схем, на которые реально ссылается WSDL.
- Модуль `<Имя>.xbsl` добавляй только если нужны SOAP headers или настройка
  подготовленного HTTP-запроса.

## Версия и источники

| Claim | Источник | Проверено | Что подтверждает |
| --- | --- | --- | --- |
| YAML-свойства SOAP-клиента | `topics/latest/soap-service-client-properties` | 2026-07-29 | `ВидЭлемента`, `UrlПоУмолчанию`, `ВерсияSoap`, `Импорт`, `ОбластьВидимости` |
| Загрузка WSDL/XSD и порождаемые методы | `topics/latest/soap-web-service-client` | 2026-07-29 | WSDL в проекте, относительные XSD/WSDL ресурсы, генерация методов и структур, call pattern |
| Ответ процедуры SOAP | `stdlib/latest/element/xbsl/Std/SoapServices/SoapResponse_ru` | 2026-07-29 | тип `ОтветSoap` |
| Ответ функции SOAP | `stdlib/latest/element/xbsl/Std/SoapServices/SoapFunctionResponse_ru` | 2026-07-29 | тип `ОтветФункцииSoap<ТипРезультата>` |
| HTTP-клиент конструктора | `stdlib/latest/element/xbsl/Std/Http/HttpClient_ru` | 2026-07-29 | тип `КлиентHttp` |

## YAML

Required:

```yaml
ВидЭлемента: КлиентSoapСервиса
Ид: <UUID>
Имя: <ИмяКлиента>
ОбластьВидимости: ВПроекте
UrlПоУмолчанию: https://partner.example/soap/orders
ВерсияSoap: Soap_1_1
```

Optional:

- `ВерсияSoap: Soap_1_2`, если WSDL и сервис используют SOAP 1.2.
- `Импорт` нужен только при ссылках на объекты другой подсистемы.

Negative:

- Не создавай клиента без WSDL: из WSDL генерируются методы операций и типы
  сообщений.
- Не переименовывай загруженные `*.Wsdl.*` и `*.Xsd.*`: платформа ожидает
  проектные имена этих ресурсов.
- Не храни учетные данные доступа в YAML или examples; настройка подключения должна
  приходить через код/окружение приложения.

## UUID

Required:

- UUID получает сам объект `КлиентSoapСервиса`.

Negative:

- WSDL/XSD resources и сгенерированные типы не получают YAML UUID.

## Imports и visibility

Required:

- `ОбластьВидимости` задавай явно.
- `Импорт` добавляй только для подсистем, чьи объекты используются в YAML или
  optional модуле клиента.

Negative:

- Не добавляй `Импорт` для `КлиентHttp`, `ОтветSoap`,
  `ОтветФункцииSoap`, `ЗаписьSoap_1_1`, `ЗаписьSoap_1_2`, `ЧтениеXml`:
  это standard library types.

## Companion artifacts

Required:

- `*.yaml` - описание клиента SOAP-сервиса.
- `*.Wsdl.1` - основное WSDL-описание сервиса.

Optional:

- `*.Xsd.*` - required only for every XSD referenced from WSDL.
- `*.Wsdl.*` с номером больше 1 - required only for every nested WSDL
  referenced from the main WSDL.
- `*.xbsl` - optional модуль клиента для настройки SOAP headers, обработки
  response headers или изменения подготовленного HTTP-запроса.

Negative:

- Отсутствующий `<Имя>.Wsdl.1` является ошибкой.
- Если `schemaLocation` или WSDL import ссылается на файл проекта, этот файл
  должен существовать рядом с клиентом.
- Optional module не должен подменять сгенерированные по WSDL operation methods.

## Генерация

Required:

- Skill создает `<Имя>.yaml`.
- Если пользователь передал WSDL/XSD содержимое, размести его в `<Имя>.Wsdl.1`
  и `<Имя>.Xsd.N` с сохранением относительных ссылок на имена файлов проекта.
- При описании вызова используй порожденный тип клиента и operation method из
  WSDL:

```xbsl
знч Клиент = новый КлиентЗаказов()
знч Ответ = Клиент.GetOrder("SO-1")
знч Номер = Ответ.Результат.Number
```

Local conventions:

- Для sample calls используй нейтральные endpoint values из пользовательского
  запроса или placeholder `partner.example`.
- Имена операций в examples синхронизируй с `wsdl:operation name`.

Negative:

- Не генерируй метод `GetOrder` вручную в модуле клиента: он создается по WSDL.
- Не добавляй SOAP headers, если пользователь не просил их или WSDL-сценарий
  их не требует.

## Валидация

Required:

- `ВидЭлемента` равен `КлиентSoapСервиса`.
- Есть `<Имя>.Wsdl.1`.
- Каждый referenced WSDL/XSD resource существует в проекте под тем именем,
  которое указано в ссылке.
- Имена operation methods в examples совпадают с `wsdl:operation name` после
  правил формирования идентификаторов платформы.
- Optional handlers в `<Имя>.xbsl` используют сгенерированные имена:
  `НастроитьЗаголовкиSoap<ИмяМетодаСервиса>`,
  `ОбработатьЗаголовкиSoap<ИмяМетодаСервиса>`,
  `ПередЗапросом<ИмяМетодаСервиса>`.

Negative:

- `missing_wsdl`.
- `missing_referenced_schema`.
- `unknown_operation_method`.
- `manual_generated_method_stub`.
