from abc import ABC
import csv
import io
import re
from datetime import datetime
from jinja2 import Template


class BaseSqlModule(ABC):
    def __init__(self, config: dict):
        self.config = config
        # Приводим ключи полей в конфигурации к нижнему регистру
        self.fields_config = {f["name"].lower(): f for f in config["fields"]}
        self.expected_fields = list(self.fields_config.keys())

    def validate_row(self, row: dict, row_idx: int) -> list:
        errors = []

        # Приводим ключи текущей строки CSV к нижнему регистру для надежного поиска
        row_lower = {k.strip().lower(): v for k, v in row.items()}

        for field_name_lower, field_rule in self.fields_config.items():
            raw_value = row_lower.get(field_name_lower)
            value = str(raw_value).strip() if raw_value is not None else ""

            # Проверка обязательных полей
            if field_rule.get("required", False) and not value:
                # Для сообщения об ошибке используем оригинальное имя из правила, если оно есть, или нижнее
                display_name = field_rule.get("name", field_name_lower)
                errors.append(f"Строка {row_idx}: Поле '{display_name}' обязательно для заполнения.")
                continue

            if not value:
                continue

            # Проверка типа, если поле не пустое
            ftype = field_rule.get("type")
            try:
                if ftype in ("int", "integer", "bigint", "biginteger"):
                    val_int = int(value)
                    if "min" in field_rule and val_int < field_rule["min"]:
                        errors.append(f"Строка {row_idx}: Поле '{field_name_lower}' меньше минимума ({field_rule['min']}).")
                    if "max" in field_rule and val_int > field_rule["max"]:
                        errors.append(f"Строка {row_idx}: Поле '{field_name_lower}' больше максимума ({field_rule['max']}).")

                elif ftype == "date":
                    datetime.strptime(value, field_rule.get("format", "%Y-%m-%d"))

                elif ftype == "string" and "regex" in field_rule:
                    if not re.match(field_rule["regex"], value):
                        errors.append(f"Строка {row_idx}: Поле '{field_name_lower}' не соответствует формату.")
            except ValueError:
                errors.append(f"Строка {row_idx}: Поле '{field_name_lower}' имеет неверный тип данных (ожидался {ftype}).")

        return errors

    def generate_sql(self, csv_file_bytes: bytes) -> tuple[str, list]:
        # 1. Проверка кодировки UTF-8
        try:
            csv_text = csv_file_bytes.decode('utf-8-sig')
        except UnicodeDecodeError:
            return "", ["Ошибка: Файл должен быть в кодировке UTF-8."]

        f = io.StringIO(csv_text)

        # 2. Проверка разделителя и структуры (через csv.Sniffer или жесткую проверку по точке с запятой)
        sample = f.readline()
        f.seek(0)

        # Проверяем, что разделитель — точка с запятой
        expected_count = len(self.expected_fields)
        if expected_count > 1 and ";" not in sample:
            return "", ["Ошибка: Неверный разделитель полей. Ожидалась точка с запятой ';'."]

        reader = csv.DictReader(f, delimiter=";")

        # 3. Проверка имен и количества полей (заголовков)

        # Приводим ожидаемые поля к нижнему регистру для сравнения
        expected_fields_lower = [f.lower() for f in self.expected_fields]

        # Получаем фактические поля из CSV, очищаем от лишних пробелов и приводим к нижнему регистру
        actual_fields = [f.strip().lower() for f in (reader.fieldnames or [])]
        if actual_fields != expected_fields_lower:
            return "", [
                f"Ошибка структуры CSV. Ожидались колонки: {self.expected_fields}, получены: {reader.fieldnames}"]

        all_errors = []
        rows_data = []

        for idx, row in enumerate(reader, start=2):  # 1 — заголовок
            row_errors = self.validate_row(row, idx)
            if row_errors:
                all_errors.extend(row_errors)
            else:
                rows_data.append(row)

        if all_errors:
            return "", all_errors

        # Рендеринг шаблона Jinja2
        with open(f"templates/{self.config['template']}", "r", encoding="utf-8") as tf:
            template = Template(tf.read())

        sql_output = template.render(rows=rows_data, generated_at=datetime.now())
        return sql_output, []