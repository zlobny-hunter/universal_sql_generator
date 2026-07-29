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

app = FastAPI(title="Modular SQL Generator")
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")

GENERATED_DIR = Path("generated")
GENERATED_DIR.mkdir(exist_ok=True)

with open("config/modules_config.yaml", "r", encoding="utf-8") as f:
    APP_CONFIG = yaml.safe_load(f)


def init_db():
    conn = sqlite3.connect("database/generator_logs.db")
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
    conn.close()


init_db()


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
    sql_code, errors = base_module.generate_sql(contents)

    conn = sqlite3.connect("database/generator_logs.db")
    cursor = conn.cursor()

    if errors:
        error_str = "\n".join(errors)
        cursor.execute(
            "INSERT INTO generation_logs (module_id, filename, status, error_message) VALUES (?, ?, ?, ?)",
            (module_id, file.filename, "ERROR", error_str)
        )
        conn.commit()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Ошибки валидации:\n{error_str}")

    # Проверка синтаксиса через sqlglot
    statements = [s.strip() for s in sql_code.split(";") if s.strip()]
    for idx, stmt in enumerate(statements, 1):
        try:
            sqlglot.parse_one(stmt, read="postgres")
        except ParseError as e:
            err_msg = f"Ошибка синтаксиса SQL (выражение #{idx}): {e}"
            cursor.execute(
                "INSERT INTO generation_logs (module_id, filename, status, error_message) VALUES (?, ?, ?, ?)",
                (module_id, file.filename, "SYNTAX_ERROR", err_msg)
            )
            conn.commit()
            conn.close()
            raise HTTPException(status_code=400, detail=err_msg)

    # Лог успешной генерации
    cursor.execute(
        "INSERT INTO generation_logs (module_id, filename, status, error_message) VALUES (?, ?, ?, ?)",
        (module_id, file.filename, "SUCCESS", None)
    )
    conn.commit()
    conn.close()

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