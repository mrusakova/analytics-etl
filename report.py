"""Сводка по витринам для сверки с отчётами «Моего Класса» (без ФИО).
Запуск на сервере:  docker compose run --rm --build etl python report.py"""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

import config as C
import db

SECTIONS = [
    ("Учеников по направлениям и статусам",
     "SELECT direction, status, COUNT(*) AS n FROM mart_student_program "
     "GROUP BY direction, status ORDER BY direction, status"),
    ("Активных учеников по направлениям и классам",
     "SELECT direction, grade, COUNT(*) AS n FROM mart_student_program WHERE status = 'active' "
     "GROUP BY direction, grade ORDER BY direction, grade"),
    ("Отказы по месяцам (дата = последнее посещение) и типам",
     "SELECT refusal_month AS month, direction, "
     "SUM(CASE WHEN refusal_type = 'no_show' THEN 1 ELSE 0 END) AS no_show, "
     "SUM(CASE WHEN refusal_type = 'after_trial' THEN 1 ELSE 0 END) AS after_trial, "
     "SUM(CASE WHEN refusal_type = 'after_month' THEN 1 ELSE 0 END) AS after_month, "
     "SUM(CASE WHEN refusal_type = 'late' THEN 1 ELSE 0 END) AS late, COUNT(*) AS total "
     "FROM mart_student_program WHERE status = 'refused' "
     "GROUP BY refusal_month, direction ORDER BY refusal_month, direction"),
    ("Движение контингента по месяцам (на начало + пришли - ушли = на конец)",
     "SELECT month, direction, SUM(start_count) AS start_cnt, SUM(came) AS came, SUM(no_show) AS no_show, "
     "SUM(after_trial) AS after_trial, SUM(after_month) AS after_month, SUM(late) AS late, "
     "SUM(completed) AS completed, SUM(end_count) AS end_cnt FROM mart_movement "
     "GROUP BY month, direction ORDER BY month, direction"),
    ("Выручка (списания) и посещения по месяцам",
     "SELECT SUBSTR(CAST(lesson_date AS TEXT), 1, 7) AS month, direction, "
     "SUM(revenue) AS revenue, SUM(visits) AS visits, SUM(absences) AS absences, "
     "SUM(CASE WHEN conducted THEN 1 ELSE 0 END) AS lessons "
     "FROM fact_lesson GROUP BY 1, direction ORDER BY 1, direction"),
    ("Долги на дату последнего снимка",
     "SELECT snapshot_date, direction, COUNT(*) AS invoices, COUNT(DISTINCT user_id) AS students, "
     "SUM(debt) AS debt, SUM(CASE WHEN overdue THEN debt ELSE 0 END) AS overdue_debt "
     "FROM debt_snapshot WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM debt_snapshot) "
     "GROUP BY snapshot_date, direction ORDER BY direction"),
    ("Группы: записи и занятия",
     "SELECT c.class_name, c.direction, c.grade, "
     "(SELECT COUNT(*) FROM mart_join j WHERE j.class_id = c.class_id "
     "  AND j.status_id IN (2, 5, 73394, 82325, 84076)) AS active_joins, "
     "(SELECT COUNT(*) FROM mart_join j WHERE j.class_id = c.class_id) AS all_joins, "
     "(SELECT COUNT(*) FROM fact_lesson l WHERE l.class_id = c.class_id AND l.conducted) AS lessons, "
     "(SELECT COUNT(*) FROM fact_lesson l WHERE l.class_id = c.class_id AND l.conducted "
     "  AND NOT l.marked) AS unmarked "
     "FROM dim_class c ORDER BY c.direction, c.grade, c.class_name"),
    # --- качество данных: всё, что ниже, в норме должно быть пустым или маленьким ---
    ("ПРОВЕРКА: группы без определённого класса (кроме дошкольников)",
     "SELECT class_name, direction FROM dim_class WHERE grade IS NULL AND direction <> 'preschool'"),
    ("ПРОВЕРКА: занятия со статусом «проведено», но без единой отметки (выручка по ним = 0)",
     "SELECT lesson_date, class_name, records FROM fact_lesson WHERE conducted AND NOT marked "
     "ORDER BY lesson_date"),
    ("ПРОВЕРКА: прошедшие занятия со статусом НЕ «проведено» (status != 1)",
     "SELECT lesson_date, class_name, records FROM fact_lesson WHERE NOT conducted "
     "AND lesson_date < :today ORDER BY lesson_date"),
    ("ПРОВЕРКА: дубли записей (ученик записан в одну группу больше одного раза)",
     "SELECT class_name, user_id, COUNT(*) AS n FROM mart_join GROUP BY class_name, user_id "
     "HAVING COUNT(*) > 1 ORDER BY n DESC"),
    ("Последние прогоны",
     "SELECT finished_at, note FROM etl_run ORDER BY finished_at DESC LIMIT 3"),
]


def print_table(title, cols, rows, limit=200):
    print(f"\n== {title} ({len(rows)})")
    if not rows:
        print("   —")
        return
    cells = [[("" if v is None else str(v)) for v in r] for r in rows[:limit]]
    w = [max(len(str(c)), *(len(r[i]) for r in cells)) for i, c in enumerate(cols)]
    print("   " + "  ".join(str(c).ljust(w[i]) for i, c in enumerate(cols)))
    for r in cells:
        print("   " + "  ".join(v.rjust(w[i]) if v.lstrip("-").isdigit() else v.ljust(w[i])
                               for i, v in enumerate(r)))
    if len(rows) > limit:
        print(f"   … ещё {len(rows) - limit}")


def main(url=C.ANALYTICS_DATABASE_URL, today=None):
    today = today or datetime.now(ZoneInfo(C.TZ)).date()
    eng = db.get_engine(url)
    with eng.connect() as conn:
        for title, sql in SECTIONS:
            res = conn.execute(text(sql), {"today": today} if ":today" in sql else {})
            print_table(title, list(res.keys()), res.all())


if __name__ == "__main__":
    main()
