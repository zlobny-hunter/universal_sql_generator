# CSV Валидация и YAML схемы

## Новые возможности

### 1. Логирование
Все ошибки и служебные сообщения (кроме консоли) записываются в лог файл:
- **Директория логов:** `logs/`
- **Формат имени файла:** `generator_YYYYMMDD.log`
- **Уровень логирования:** DEBUG

Логирование включает:
- Информацию о начале обработки файлов
- Ошибки валидации (кодировка, разделители, структура)
- Предупреждения о проблемах с данными
- Успешные генерации SQL

### 2. ValIdация с frictionless
Интегрирована библиотека `frictionless` для расширенной валидации CSV файлов:
- Поддержка YAML схем для каждого модуля
- Валидация типов данных
- Проверка обязательных полей
- Валидация по регулярным выражениям

### 3. YAML схемы

Каждый модуль может иметь свою YAML схему в директории `schemas/`:

```
schemas/
├── users_import.yaml
├── insert_UV.yaml
├── apteka_filial.yaml
└── ...
```

#### Структура YAML схемы:
```yaml
fields:
  - name: field_name
    type: string|integer|date
    constraints:
      required: true
      pattern: '^regex_pattern$'
      minimum: 0
      maximum: 100
```

#### Поддерживаемые типы:
- `string` - строка
- `integer` - целое число
- `date` - дата (формат в поле `format`)

#### Поддерживаемые ограничения:
- `required` - обязательное поле
- `pattern` - регулярное выражение для валидации
- `minimum` - минимальное значение для чисел
- `maximum` - максимальное значение для чисел

## Использование

### Создание схемы для модуля

1. Определите имя вашего модуля (например, `my_module`)
2. Создайте файл `schemas/my_module.yaml`
3. Заполните схему согласно структуре выше

### Пример: users_import.yaml

```yaml
fields:
  - name: email
    type: string
    constraints:
      required: true
      pattern: '^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'

  - name: age
    type: integer
    constraints:
      minimum: 18
      maximum: 100

  - name: registration_date
    type: date
    constraints:
      required: true
```

## Просмотр логов

Логи хранятся в файлах формата `logs/generator_YYYYMMDD.log`:

```bash
# Просмотр логов текущего дня
cat logs/generator_*.log

# Поиск ошибок
grep "ERROR" logs/generator_*.log

# Поиск предупреждений
grep "WARNING" logs/generator_*.log
```

## Примеры вывода логов

```
2024-12-01 10:15:30 - sql_generator - INFO - Начало обработки файла: users.csv
2024-12-01 10:15:30 - sql_generator - INFO - Схема загружена из schemas/users_import.yaml
2024-12-01 10:15:30 - sql_generator - INFO - Валидация frictionless для users.csv: valid=True
2024-12-01 10:15:30 - sql_generator - INFO - SQL успешно сгенерирован для файла users.csv. Строк обработано: 150
```

## Миграция существующего кода

Если вы используете `BaseSqlModule` в своем коде, обновите вызовы:

### До:
```python
base_module = BaseSqlModule(config)
sql_code, errors = base_module.generate_sql(csv_bytes)
```

### После:
```python
base_module = BaseSqlModule(config)
sql_code, errors = base_module.generate_sql(csv_bytes, filename="file.csv")
```

Параметр `filename` используется в логах для идентификации файла.

## Требования

Убедитесь, что установлены все зависимости:

```bash
pip install -r requirements.txt
```

Новые зависимости:
- `frictionless==5.16.1`
- `PyYAML==6.0.1` (уже был)
