from abc import ABC
import csv
import io
import re
import logging
import yaml
from datetime import datetime
from pathlib import Path
from jinja2 import Template, Environment
from frictionless import Resource, validate, Report, Schema


def get_project_root() -> Path:
    """Get the project root directory"""
    return Path(__file__).parent.parent


class LoggerSetup:
    """Настройка логирования для модуля"""
    _loggers = {}
    _lock = None

    @classmethod
    def _get_lock(cls):
        """Thread-safe lazy initialization of lock"""
        if cls._lock is None:
            import threading
            cls._lock = threading.Lock()
        return cls._lock

    @classmethod
    def get_logger(cls, name: str = "sql_generator") -> logging.Logger:
        with cls._get_lock():
            if name not in cls._loggers:
                project_root = get_project_root()
                logs_dir = project_root / "logs"
                logs_dir.mkdir(exist_ok=True)

                logger = logging.getLogger(name)
                logger.setLevel(logging.DEBUG)

                # Файловый обработчик
                log_file = logs_dir / f"generator_{datetime.now().strftime('%Y%m%d')}.log"
                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setLevel(logging.DEBUG)

                # Форматер
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)

                cls._loggers[name] = logger

        return cls._loggers[name]


class BaseSqlModule(ABC):
    _template_cache = {}

    def __init__(self, config: dict, schema_path: str = None):
        self.config = config
        self.logger = LoggerSetup.get_logger()
        self.schema_path = schema_path or self._get_default_schema_path()
        self.schema = self._load_schema()

        # Приводим ключи полей в конфигурации к нижнему регистру
        self.fields_config = {f["name"].lower(): f for f in config["fields"]}
        self.expected_fields = list(self.fields_config.keys())

    def _get_default_schema_path(self) -> str:
        """Получить путь к схеме по умолчанию на основе module_id"""
        module_id = self.config.get("id", "default")
        project_root = get_project_root()
        schema_file = project_root / "schemas" / f"{module_id}.yaml"
        if schema_file.exists():
            return str(schema_file)
        return None

    def _load_schema(self) -> Schema:
        """Загрузить схему из YAML файла"""
        if not self.schema_path:
            return None

        try:
            with open(self.schema_path, "r", encoding="utf-8") as f:
                schema_dict = yaml.safe_load(f)
                schema = Schema(schema_dict)
                self.logger.info(f"Схема загружена из {self.schema_path}")
                return schema
        except FileNotFoundError:
            self.logger.warning(f"Файл схемы не найден: {self.schema_path}")
            return None
        except yaml.YAMLError as e:
            self.logger.error(f"Ошибка при загрузке YAML схемы: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Ошибка при создании Schema объекта: {e}")
            return None

    def _validate_with_frictionless(self, csv_file_bytes: bytes, filename: str) -> tuple[bool, list]:
        """Валидация CSV с использованием frictionless"""
        try:
            csv_text = csv_file_bytes.decode('utf-8-sig')
        except UnicodeDecodeError as e:
            error_msg = "Файл должен быть в кодировке UTF-8"
            self.logger.error(f"{error_msg}: {e}")
            return False, [error_msg]

        # Сохраняем временный CSV для валидации
        project_root = get_project_root()
        temp_csv_path = project_root / ".temp_csv_validation"
        try:
            with open(temp_csv_path, "w", encoding="utf-8") as f:
                f.write(csv_text)

            # Если есть схема YAML, используем её для валидации
            if self.schema:
                resource = Resource(str(temp_csv_path), schema=self.schema)
            else:
                resource = Resource(str(temp_csv_path))

            report: Report = validate(resource)
            self.logger.info(f"Валидация frictionless для {filename}: valid={report.valid}")

            errors = []
            if not report.valid:
                for task in report.tasks:
                    for error in task.errors:
                        error_msg = f"Ошибка frictionless: {error.message}"
                        errors.append(error_msg)
                        self.logger.warning(error_msg)

            return report.valid, errors

        except Exception as e:
            error_msg = f"Ошибка при валидации frictionless: {str(e)}"
            self.logger.error(error_msg)
            # Не прерываем работу, продолжаем с внутренней валидацией
            return True, []
        finally:
            if temp_csv_path.exists():
                temp_csv_path.unlink()

    def validate_row(self, row: dict, row_idx: int) -> list:
        """Валидация отдельной строки CSV"""
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
                error_msg = f"Строка {row_idx}: Поле '{display_name}' обязательно для заполнения."
                errors.append(error_msg)
                self.logger.warning(error_msg)
                continue

            if not value:
                continue

            # Проверка типа, если поле не пустое
            ftype = field_rule.get("type")
            try:
                if ftype in ("int", "integer", "bigint", "biginteger"):
                    val_int = int(value)
                    # Проверка regex для integer типов
                    if "regex" in field_rule and not re.match(field_rule["regex"], value):
                        error_msg = f"Строка {row_idx}: Поле '{field_name_lower}' не соответствует формату."
                        errors.append(error_msg)
                        self.logger.warning(error_msg)
                    if "min" in field_rule and val_int < field_rule["min"]:
                        error_msg = f"Строка {row_idx}: Поле '{field_name_lower}' меньше минимума ({field_rule['min']})."
                        errors.append(error_msg)
                        self.logger.warning(error_msg)
                    if "max" in field_rule and val_int > field_rule["max"]:
                        error_msg = f"Строка {row_idx}: Поле '{field_name_lower}' больше максимума ({field_rule['max']})."
                        errors.append(error_msg)
                        self.logger.warning(error_msg)

                elif ftype == "date":
                    datetime.strptime(value, field_rule.get("format", "%Y-%m-%d"))

                elif ftype == "string" and "regex" in field_rule:
                    if not re.match(field_rule["regex"], value):
                        error_msg = f"Строка {row_idx}: Поле '{field_name_lower}' не соответствует формату."
                        errors.append(error_msg)
                        self.logger.warning(error_msg)
            except ValueError:
                error_msg = f"Строка {row_idx}: Поле '{field_name_lower}' имеет неверный тип данных (ожидался {ftype})."
                errors.append(error_msg)
                self.logger.error(error_msg)

        return errors

    def generate_sql(self, csv_file_bytes: bytes, filename: str = "file.csv") -> tuple[str, list]:
        """Генерация SQL из CSV файла с полной валидацией"""
        self.logger.info(f"Начало обработки файла: {filename}")

        # 1. Валидация с frictionless (если есть схема)
        if self.schema:
            is_valid, frictionless_errors = self._validate_with_frictionless(csv_file_bytes, filename)
            if frictionless_errors:
                self.logger.error(f"Ошибки валидации frictionless: {frictionless_errors}")
                return "", frictionless_errors

        # 2. Проверка кодировки UTF-8
        try:
            csv_text = csv_file_bytes.decode('utf-8-sig')
        except UnicodeDecodeError:
            error_msg = "Ошибка: Файл должен быть в кодировке UTF-8."
            self.logger.error(error_msg)
            return "", [error_msg]

        f = io.StringIO(csv_text)

        # 3. Проверка разделителя и структуры
        sample = f.readline()
        f.seek(0)

        # Проверяем, что разделитель — точка с запятой
        expected_count = len(self.expected_fields)
        if expected_count > 1 and ";" not in sample:
            error_msg = "Ошибка: Неверный разделитель полей. Ожидалась точка с запятой ';'."
            self.logger.error(error_msg)
            return "", [error_msg]

        reader = csv.DictReader(f, delimiter=";")

        # 4. Проверка имен и количества полей (заголовков)
        expected_fields_lower = [f.lower() for f in self.expected_fields]
        actual_fields = [f.strip().lower() for f in (reader.fieldnames or [])]

        if actual_fields != expected_fields_lower:
            error_msg = f"Ошибка структуры CSV. Ожидались колонки: {self.expected_fields}, получены: {reader.fieldnames}"
            self.logger.error(error_msg)
            return "", [error_msg]

        all_errors = []
        rows_data = []

        # 5. Валидация строк
        for idx, row in enumerate(reader, start=2):  # 1 — заголовок
            row_errors = self.validate_row(row, idx)
            if row_errors:
                all_errors.extend(row_errors)
            else:
                rows_data.append(row)

        if all_errors:
            self.logger.error(f"Обнаружено {len(all_errors)} ошибок валидации")
            return "", all_errors

        # 6. Рендеринг шаблона Jinja2 с кешированием
        try:
            template_name = self.config['template']
            if template_name not in self._template_cache:
                project_root = get_project_root()
                template_path = project_root / "templates" / template_name
                with open(template_path, "r", encoding="utf-8") as tf:
                    # Используем Environment для autoescape
                    env = Environment(autoescape=True)
                    self._template_cache[template_name] = env.from_string(tf.read())

            template = self._template_cache[template_name]
            sql_output = template.render(rows=rows_data, generated_at=datetime.now())
            self.logger.info(f"SQL успешно сгенерирован для файла {filename}. Строк обработано: {len(rows_data)}")
            return sql_output, []
        except FileNotFoundError as e:
            error_msg = f"Ошибка: Шаблон не найден - {e}"
            self.logger.error(error_msg)
            return "", [error_msg]
        except Exception as e:
            error_msg = f"Ошибка при рендеринге шаблона: {e}"
            self.logger.error(error_msg)
            return "", [error_msg]