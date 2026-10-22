"""Настройки загрузчика аналитики. Всё берётся из переменных окружения (.env)."""
import os

MOYKLASS_API_KEY = os.environ.get("MOYKLASS_API_KEY", "")
# Куда писать витрины для DataLens (Yandex Managed PostgreSQL), например:
# postgresql+psycopg://user:pass@rc1a-xxxx.mdb.yandexcloud.net:6432/analytics?sslmode=require


def _db_url():
    """Либо готовый ANALYTICS_DATABASE_URL, либо параметры по отдельности (PGHOST...) —
    так пароль со спецсимволами не нужно кодировать вручную."""
    if os.environ.get("ANALYTICS_DATABASE_URL"):
        return os.environ["ANALYTICS_DATABASE_URL"]
    if os.environ.get("PGHOST"):
        from sqlalchemy.engine import URL
        return URL.create("postgresql+psycopg", username=os.environ.get("PGUSER", "analytics"),
                          password=os.environ.get("PGPASSWORD", ""), host=os.environ["PGHOST"],
                          port=int(os.environ.get("PGPORT", "6432")),
                          database=os.environ.get("PGDATABASE", "analytics"),
                          query={"sslmode": "require"}).render_as_string(hide_password=False)
    return "sqlite:///analytics_local.db"


ANALYTICS_DATABASE_URL = _db_url()

SEASON_MARKER = os.environ.get("SEASON_MARKER", "26/27")      # учебный год — по названию группы
SEASON_START = os.environ.get("SEASON_START", "2026-08-01")   # с какой даты тянуть занятия
# Начало занятий: отказы, случившиеся раньше (записались на год заранее и передумали),
# относим к этому месяцу (refusal_month); настоящая дата остаётся в refusal_date.
CLASSES_START = os.environ.get("CLASSES_START", "2026-09-01")
TZ = os.environ.get("TZ_NAME", "Europe/Moscow")

# Статусы записей в группу (справочник joinStatuses)
ST_REFUSED = 1            # Отказался
ST_LEARNING = 2           # Учится
ST_DONE_OR_MOVED = 4      # Завершил / зап. в др. группу
ST_MAKEUP = 5             # Отработка
ST_ENROLLED = 73394       # Записан
ST_NOT_ATTENDING = 82325  # Не ходит? (в показателях не используем -> считаем активной)
ST_ACCEPTED = 84076       # Зачислен
ACTIVE_STATUSES = {ST_LEARNING, ST_MAKEUP, ST_ENROLLED, ST_NOT_ATTENDING, ST_ACCEPTED}

# Пороги: (макс. посещений для "после пробного", макс. для "после месяца")
THRESH_YOUNG = (2, 5)   # дошкольники, 1-4 кл, Школа+
THRESH_OLDER = (2, 9)   # 5-11 кл
# Риск оттока: сколько пропусков за 7 дней
RISK_ABSENCES_YOUNG = 1
RISK_ABSENCES_OLDER = 2
RISK_WINDOW_DAYS = 7
# Пропуски по уважительной причине (goodReason) в риск оттока не входят.
