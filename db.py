"""Таблицы-витрины для DataLens (SQLAlchemy Core: PostgreSQL в проде, SQLite в тестах)."""
from sqlalchemy import (BigInteger, Boolean, Column, Date, DateTime, Integer, MetaData,
                        String, Table, create_engine, delete)

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


def create_views(conn):
    from sqlalchemy import text
    for name, sql in VIEWS.items():
        conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
        conn.execute(text(f"CREATE VIEW {name} AS {sql}"))
