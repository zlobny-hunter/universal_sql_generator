from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
import sqlite3
import yaml
from pathlib import Path
import time
import sqlglot
from sqlglot.errors import ParseError
from datetime import datetime


def get_project_root() -> Path:
    """Get the project root directory"""
    return Path(__file__).parent.parent

app = FastAPI(title="Modular SQL Generator")
from fastapi.staticfiles import StaticFiles

project_root = get_project_root()
app.mount("/static", StaticFiles(directory=str(project_root / "web" / "static")), name="static")
templates = Jinja2Templates(directory=str(project_root / "web" / "templates"))

GENERATED_DIR = project_root / "generated"
GENERATED_DIR.mkdir(exist_ok=True)

with open(project_root / "config" / "modules_config.yaml", "r", encoding="utf-8") as f:
    APP_CONFIG = yaml.safe_load(f)


def init_db():
    with sqlite3.connect(str(project_root / "database" / "generator_logs.db")) as conn:
        cursor = conn.cursor()
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS generation_logs
                       (
                           id            INTEGER PRIMARY KEY AUTOINCREMENT,
                           module_id     TEXT,
                           filename      TEXT,
                           status        TEXT,
                           error_message TEXT,
                           created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                       )
                       """)
        conn.commit()


init_db()


def log_generation(module_id: str, filename: str, status: str, error_message: str = None):
    """Helper function to log generation results to database"""
    with sqlite3.connect(str(project_root / "database" / "generator_logs.db")) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO generation_logs (module_id, filename, status, error_message) VALUES (?, ?, ?, ?)",
            (module_id, filename, status, error_message)
        )
        conn.commit()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "modules": APP_CONFIG["modules"]})


@app.post("/generate/")
async def generate_sql(
        module_id: str = Form(...),
        file: UploadFile = File(...)
):
    mod_cfg = next((m for m in APP_CONFIG["modules"] if m["id"] == module_id), None)
    if not mod_cfg:
        raise HTTPException(status_code=400, detail="Модуль не найден")

    contents = await file.read()

    from modules.base import BaseSqlModule
    base_module = BaseSqlModule(mod_cfg)
    sql_code, errors = base_module.generate_sql(contents, filename=file.filename)

    if errors:
        error_str = "\n".join(errors)
        log_generation(module_id, file.filename, "ERROR", error_str)
        raise HTTPException(status_code=400, detail=f"Ошибки валидации:\n{error_str}")

    # Проверка синтаксиса через sqlglot
    sql_dialect = mod_cfg.get("sql_dialect", "postgres")
    statements = [s.strip() for s in sql_code.split(";") if s.strip()]
    for idx, stmt in enumerate(statements, 1):
        try:
            sqlglot.parse_one(stmt, read=sql_dialect)
        except ParseError as e:
            err_msg = f"Ошибка синтаксиса SQL (выражение #{idx}): {e}"
            log_generation(module_id, file.filename, "SYNTAX_ERROR", err_msg)
            raise HTTPException(status_code=400, detail=err_msg)

    # Лог успешной генерации
    log_generation(module_id, file.filename, "SUCCESS", None)

    # Формирование имени файла и сохранение на диск для скачивания
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_filename = mod_cfg.get("output_filename", "script_{timestamp}.sql").format(timestamp=timestamp)
    out_file_path = GENERATED_DIR / out_filename

    with open(out_file_path, "w", encoding="utf-8") as f:
        f.write(sql_code)

    # Принудительный запуск скачивания файла браузером
    return FileResponse(
        path=out_file_path,
        filename=out_filename,
        media_type="application/sql"
    )