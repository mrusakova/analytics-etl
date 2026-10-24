"""Выгрузка для отчёта «нагрузка на преподавателей»: занятия кружков 1–11 кл (без Школы+)
с числом посещений и преподавателей. Сводную таблицу по неделям собирают из этого TSV.
Запуск на сервере:  docker compose run --rm --build etl python teacher_load.py > teacher_load.tsv"""
import sys

from sqlalchemy import text

import config as C
import db

SQL = """
SELECT c.class_id, c.class_name, c.status, c.course_name, o.group_order,
       l.lesson_date, l.conducted, l.marked, l.visits, t.teachers
FROM dim_class c
JOIN fact_lesson l ON l.class_id = c.class_id
LEFT JOIN fact_lesson_staff t ON t.lesson_id = l.lesson_id
LEFT JOIN dim_group_order o ON o.class_id = c.class_id
WHERE c.course_name LIKE 'Кружки%класс%' AND c.class_name NOT LIKE '%Школа+%'
  AND l.lesson_date >= :since
ORDER BY o.group_order, l.lesson_date
"""


def main(since="2026-09-21"):
    eng = db.get_engine(C.ANALYTICS_DATABASE_URL)
    with eng.connect() as conn:
        rows = conn.execute(text(SQL), {"since": since}).all()
    cols = ["class_id", "class_name", "status", "course_name", "group_order",
            "lesson_date", "conducted", "marked", "visits", "teachers"]
    print("\t".join(cols))
    for r in rows:
        print("\t".join("" if v is None else str(v) for v in r))


if __name__ == "__main__":
    main(*sys.argv[1:])
