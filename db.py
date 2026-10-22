"""Таблицы-витрины для DataLens (SQLAlchemy Core: PostgreSQL в проде, SQLite в тестах)."""
from sqlalchemy import (BigInteger, Boolean, Column, Date, DateTime, Integer, MetaData,
                        String, Table, create_engine, delete)

import config as C

md = MetaData()
I = BigInteger

dim_class = Table("dim_class", md,
    Column("class_id", I, primary_key=True), Column("class_name", String), Column("status", String),
    Column("direction", String), Column("grade", Integer), Column("course_name", String))

fact_lesson = Table("fact_lesson", md,   # одна строка = проведённое/запланированное занятие группы
    Column("lesson_id", I, primary_key=True), Column("lesson_date", Date), Column("class_id", I),
    Column("class_name", String), Column("direction", String), Column("grade", Integer),
    Column("conducted", Boolean), Column("marked", Boolean),
    Column("records", Integer), Column("visits", Integer),
    Column("absences", Integer), Column("absences_good_reason", Integer),
    Column("revenue", Integer))   # выручка = сумма списаний за занятие

mart_join = Table("mart_join", md,       # записи в группы
    Column("join_id", I, primary_key=True), Column("user_id", I), Column("class_id", I),
    Column("class_name", String), Column("direction", String), Column("grade", Integer),
    Column("status_id", I), Column("status_name", String), Column("created_at", Date),
    Column("state_changed_at", Date), Column("reason_id", I))

mart_student_program = Table("mart_student_program", md,   # ученик x направление
    Column("user_id", I, primary_key=True), Column("direction", String, primary_key=True),
    Column("grade", Integer), Column("status", String), Column("visits", Integer),
    Column("first_visit", Date), Column("last_visit", Date), Column("joined_at", Date),
    Column("refusal_type", String), Column("refusal_date", Date), Column("refusal_month", Date),
    Column("reason_id", I), Column("groups_count", Integer))

mart_churn_risk = Table("mart_churn_risk", md,
    Column("user_id", I, primary_key=True), Column("direction", String, primary_key=True),
    Column("grade", Integer), Column("absences_7d", Integer), Column("visits", Integer),
    Column("last_visit", Date))

debt_snapshot = Table("debt_snapshot", md,   # снимок долгов, копится по понедельникам
    Column("snapshot_date", Date, primary_key=True), Column("invoice_id", I, primary_key=True),
    Column("user_id", I), Column("class_id", I), Column("direction", String), Column("grade", Integer),
    Column("price", Integer), Column("payed", Integer), Column("debt", Integer),
    Column("pay_until", Date), Column("overdue", Boolean))

group_snapshot = Table("group_snapshot", md,   # записи по группам на дату
    Column("snapshot_date", Date, primary_key=True), Column("class_id", I, primary_key=True),
    Column("direction", String), Column("grade", Integer),
    Column("active_joins", Integer), Column("total_joins", Integer))

dim_students = Table("dim_students", md,   # имена — ТОЛЬКО для закрытого набора данных
    Column("user_id", I, primary_key=True), Column("name", String))

etl_run = Table("etl_run", md, Column("finished_at", DateTime, primary_key=True),
                Column("note", String))


def get_engine(url: str):
    return create_engine(url, future=True)


def replace_all(conn, table, rows):
    conn.execute(delete(table))
    if rows:
        conn.execute(table.insert(), rows)


def replace_snapshot(conn, table, snap_date, rows):
    conn.execute(delete(table).where(table.c.snapshot_date == snap_date))
    if rows:
        conn.execute(table.insert(), rows)


# Представления С ИМЕНАМИ — для закрытых наборов данных в DataLens (списки «кому звонить»).
# Основные таблицы витрин имён не содержат.
VIEWS = {
    "v_student_program_named": "SELECT s.*, n.name AS student_name FROM mart_student_program s "
                               "LEFT JOIN dim_students n ON n.user_id = s.user_id",
    "v_churn_risk_named": "SELECT r.*, n.name AS student_name FROM mart_churn_risk r "
                          "LEFT JOIN dim_students n ON n.user_id = r.user_id",
    "v_debt_named": "SELECT d.*, n.name AS student_name FROM debt_snapshot d "
                    "LEFT JOIN dim_students n ON n.user_id = d.user_id",
}

# --- Представления для DataLens: русские подписи, чтобы коллеги собирали чарты без кодов. ---
# v_dl_* — без имён (общий дашборд); v_dl_*_named — с ФИО (закрытый воркбук).


def _dir(c):
    return (f"CASE {c} WHEN 'olymp' THEN 'Олимпиадная математика' WHEN 'school_plus' THEN 'Школа+' "
            f"WHEN 'preschool' THEN 'Дошкольники' ELSE {c} END")


def _grade(d, g):   # подпись класса; для сортировки в DataLens есть числовой grade
    return (f"CASE WHEN {d} = 'preschool' THEN 'Дошкольники' WHEN {g} IS NULL THEN '?' "
            f"ELSE CAST({g} AS VARCHAR) || ' кл' END")


_ACTIVE = ", ".join(str(s) for s in sorted(C.ACTIVE_STATUSES))

VIEWS.update({
    "v_dl_lessons":   # занятия: выручка, посещения, пропуски по дате
        f"SELECT l.lesson_date, l.class_id, l.class_name, {_dir('l.direction')} AS direction_name, "
        f"l.grade, {_grade('l.direction', 'l.grade')} AS grade_label, l.conducted, l.records, l.visits, "
        f"l.absences, l.absences_good_reason, l.revenue FROM fact_lesson l",
    "v_dl_students":  # ученик x направление: статус, отказы
        f"SELECT s.user_id, {_dir('s.direction')} AS direction_name, s.grade, "
        f"{_grade('s.direction', 's.grade')} AS grade_label, "
        f"CASE s.status WHEN 'active' THEN 'Учится' WHEN 'refused' THEN 'Отказ' "
        f"ELSE 'Завершил / перешёл' END AS status_name, "
        f"CASE s.refusal_type WHEN 'no_show' THEN '1. Не дошёл' WHEN 'after_trial' THEN '2. После пробного' "
        f"WHEN 'after_month' THEN '3. После месяца' WHEN 'late' THEN '4. Поздний' END AS refusal_type_name, "
        f"s.refusal_date, s.refusal_month, s.visits, s.first_visit, s.last_visit, s.joined_at, s.groups_count "
        f"FROM mart_student_program s",
    "v_dl_joins":     # записи в группы (текущее состояние)
        f"SELECT j.join_id, j.user_id, j.class_id, j.class_name, {_dir('j.direction')} AS direction_name, "
        f"j.grade, {_grade('j.direction', 'j.grade')} AS grade_label, j.status_name, "
        f"CASE WHEN j.status_id IN ({_ACTIVE}) THEN 1 ELSE 0 END AS is_active, "
        f"j.created_at, j.state_changed_at FROM mart_join j",
    "v_dl_groups_weekly":   # записи по группам на каждый понедельник (динамика)
        f"SELECT g.snapshot_date, g.class_id, c.class_name, {_dir('g.direction')} AS direction_name, "
        f"g.grade, {_grade('g.direction', 'g.grade')} AS grade_label, g.active_joins, g.total_joins, "
        f"CASE WHEN g.snapshot_date = (SELECT MAX(snapshot_date) FROM group_snapshot) THEN 1 ELSE 0 END "
        f"AS is_latest FROM group_snapshot g LEFT JOIN dim_class c ON c.class_id = g.class_id",
    "v_dl_debts":     # долги по счетам на каждый понедельник
        f"SELECT d.snapshot_date, d.invoice_id, d.user_id, d.class_id, c.class_name, "
        f"{_dir('d.direction')} AS direction_name, d.grade, {_grade('d.direction', 'd.grade')} AS grade_label, "
        f"d.price, d.payed, d.debt, CASE WHEN d.overdue THEN d.debt ELSE 0 END AS overdue_debt, "
        f"d.pay_until, d.overdue, "
        f"CASE WHEN d.snapshot_date = (SELECT MAX(snapshot_date) FROM debt_snapshot) THEN 1 ELSE 0 END "
        f"AS is_latest FROM debt_snapshot d LEFT JOIN dim_class c ON c.class_id = d.class_id",
    "v_dl_last_run":  # «данные на …» для шапки дашборда
        "SELECT MAX(finished_at) AS updated_at FROM etl_run",
    # --- закрытые, с ФИО ---
    "v_dl_students_named":
        "SELECT s.*, n.name AS student_name FROM v_dl_students s LEFT JOIN dim_students n ON n.user_id = s.user_id",
    "v_dl_debts_named":
        "SELECT d.*, n.name AS student_name FROM v_dl_debts d LEFT JOIN dim_students n ON n.user_id = d.user_id",
    "v_dl_risk_named":   # риск оттока: кому звонить
        f"SELECT r.user_id, n.name AS student_name, {_dir('r.direction')} AS direction_name, r.grade, "
        f"{_grade('r.direction', 'r.grade')} AS grade_label, r.absences_7d, r.visits, r.last_visit "
        f"FROM mart_churn_risk r LEFT JOIN dim_students n ON n.user_id = r.user_id",
})


def create_views(conn):
    from sqlalchemy import text
    # Удаляем в обратном порядке: *_named зависят от v_dl_* (PostgreSQL не даст удалить базовое раньше).
    for name in reversed(list(VIEWS)):
        conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
    for name, sql in VIEWS.items():
        conn.execute(text(f"CREATE VIEW {name} AS {sql}"))
