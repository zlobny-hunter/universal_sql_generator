from abc import ABC
import csv
import io
import re
from datetime import datetime
from jinja2 import Template


class BaseSqlModule(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.fields_config = {f["name"]: f for f in config["fields"]}
        self.expected_fields = list(self.fields_config.keys())

    def validate_row(self, row: dict, row_idx: int) -> list:
        errors = []
        for field_name, field_rule in self.fields_config.items():
            value = row.get(field_name, "").strip()

            # Проверка обязательных полей
            if field_rule.get("required", False) and not value:
                errors.append(f"Строка {row_idx}: Поле '{field_name}' обязательно для заполнения.")
                continue

            # Если поле пустое и необязательное — пропускаем проверку типов
            if not value:
                continue

            # Проверка типа, если поле не пустое
            ftype = field_rule.get("type")
            try:
                if ftype == "integer":
                    val_int = int(value)
                    if "min" in field_rule and val_int < field_rule["min"]:
                        errors.append(f"Строка {row_idx}: Поле '{field_name}' меньше минимума ({field_rule['min']}).")
                    if "max" in field_rule and val_int > field_rule["max"]:
                        errors.append(f"Строка {row_idx}: Поле '{field_name}' больше максимума ({field_rule['max']}).")

                elif ftype == "date":
                    datetime.strptime(value, field_rule.get("format", "%Y-%m-%d"))

                elif ftype == "string" and "regex" in field_rule:
                    if not re.match(field_rule["regex"], value):
                        errors.append(f"Строка {row_idx}: Поле '{field_name}' не соответствует формату.")
            except ValueError:
                errors.append(f"Строка {row_idx}: Поле '{field_name}' имеет неверный тип данных (ожидался {ftype}).")

        return errors

    def generate_sql(self, csv_file_bytes: bytes) -> tuple[str, list]:
        # 1. Проверка кодировки UTF-8
        try:
            csv_text = csv_file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            return "", ["Ошибка: Файл должен быть в кодировке UTF-8."]

        f = io.StringIO(csv_text)

        # 2. Проверка разделителя и структуры (через csv.Sniffer или жесткую проверку по точке с запятой)
        sample = f.read(2048)
        f.seek(0)

        # Проверяем, что разделитель — точка с запятой
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        if dialect.delimiter != ";":
            return "", [
                f"Ошибка: Неверный разделитель полей. Ожидалась точка с запятой ';', обнаружен '{dialect.delimiter}'."]

        reader = csv.DictReader(f, delimiter=";")

        # 3. Проверка имен и количества полей (заголовков)
        actual_fields = reader.fieldnames or []
        if actual_fields != self.expected_fields:
            return "", [f"Ошибка структуры CSV. Ожидались колонки: {self.expected_fields}, получены: {actual_fields}"]

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