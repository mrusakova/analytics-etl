"""Ежедневная загрузка: Мой Класс -> витрины в PostgreSQL для DataLens.
Запуск:  python etl.py            (обычный прогон; по понедельникам ещё и снимки)
         python etl.py --snapshot (принудительно сделать снимок долгов/групп сегодня)"""
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import config as C
import db
from classify import build_student_programs, direction_of, movement_rows, risk_rows
from mk_client import MoyKlass

STATUS_NAMES = {1: "Отказался", 2: "Учится", 4: "Завершил/зап. в др. группу", 5: "Отработка",
                73394: "Записан", 82325: "Не ходит?", 84076: "Зачислен"}


def _d(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date() if s else None


def extract(mk: MoyKlass, today: date):
    # /company/courses и /company/classes отдают ГОЛЫЙ массив целиком (limit/offset не
    # учитываются — проверено вживую), остальные списки — объект с ключом (joins, lessons...).
    courses = {c["id"]: c["name"] for c in mk.get("/company/courses")}
    classes = [c for c in mk.get("/company/classes") if C.SEASON_MARKER in (c.get("name") or "")]
    meta, dim = {}, []
    for c in classes:
        res = direction_of(c["name"], c["courseId"], courses.get(c["courseId"], ""))
        if not res:
            continue
        direction, grade = res
        meta[c["id"]] = dict(direction=direction, grade=grade, name=c["name"])
        dim.append(dict(class_id=c["id"], class_name=c["name"], status=c["status"], direction=direction,
                        grade=grade, course_name=courses.get(c["courseId"])))
    joins, lessons, subs = [], [], []
    for cid in meta:
        joins += mk.paged("/company/joins", "joins", classId=cid)
        # Диапазон дат (2 значения) у /company/lessons на практике не проходит валидацию
        # (см. бота, student_card.py) — берём все занятия группы по дате и режем сами.
        lessons += [L for L in mk.paged("/company/lessons", "lessons", limit=100, classId=cid,
                                        includeRecords="true", sort="date", sortDirection="asc")
                    if C.SEASON_START <= (L.get("date") or "") <= today.isoformat()]
        subs += mk.paged("/company/userSubscriptions", "subscriptions", classId=cid)
    # У /company/invoices нет фильтра по группе — берём все счета один раз (~18 тыс.),
    # к группам они привязываются в transform через абонемент или запись (joinId).
    invoices = mk.paged("/company/invoices", "invoices")
    return dim, meta, joins, lessons, invoices, subs


def transform(meta, joins, lessons, invoices, subs, today: date):
    visit_dates, absence_dates = defaultdict(list), defaultdict(list)
    fact = []
    for L in lessons:
        m = meta.get(L["classId"])
        if not m:
            continue
        ld = _d(L["date"])
        recs = L.get("records") or []
        conducted = L.get("status") == 1 and ld <= today
        marked = conducted and any(r["visit"] for r in recs)   # защита от неотмеченных занятий
        visits = absent = absent_good = rev = 0
        for r in recs:
            if not marked:
                continue
            key = (r["userId"], m["direction"])
            rev += (r.get("bill") or {}).get("summa") or 0
            if r["visit"]:
                visits += 1
                visit_dates[key].append(ld)
            elif r.get("goodReason"):
                absent_good += 1
            elif not r.get("free") and not r.get("test"):
                absent += 1
                absence_dates[key].append(ld)
        fact.append(dict(lesson_id=L["id"], lesson_date=ld, class_id=L["classId"], class_name=m["name"],
                         direction=m["direction"], grade=m["grade"], conducted=conducted, marked=marked,
                         records=len(recs), visits=visits, absences=absent,
                         absences_good_reason=absent_good, revenue=rev))
    students = build_student_programs(joins, meta, visit_dates)
    risk = risk_rows(students, absence_dates, today)
    mj = []
    for j in joins:
        m = meta[j["classId"]]
        mj.append(dict(join_id=j["id"], user_id=j["userId"], class_id=j["classId"], class_name=m["name"],
                       direction=m["direction"], grade=m["grade"], status_id=j["statusId"],
                       status_name=STATUS_NAMES.get(j["statusId"], str(j["statusId"])),
                       created_at=_d(j["createdAt"]), state_changed_at=_d(j["stateChangedAt"]),
                       reason_id=j.get("statusChangeReasonId")))
    sub_class = {s["id"]: s.get("mainClassId") for s in subs}
    join_class = {j["id"]: j["classId"] for j in joins}   # счета с оплатой «единой суммой»
    debts = []
    for inv in invoices:
        cid = sub_class.get(inv.get("userSubscriptionId")) or join_class.get(inv.get("joinId"))
        m = meta.get(cid)
        debt = (inv["price"] or 0) - (inv["payed"] or 0)
        if m and debt > 0:
            pu = _d(inv.get("payUntil"))
            debts.append(dict(snapshot_date=today, invoice_id=inv["id"], user_id=inv["userId"], class_id=cid,
                              direction=m["direction"], grade=m["grade"], price=inv["price"], payed=inv["payed"],
                              debt=debt, pay_until=pu, overdue=bool(pu and pu < today)))
    per_class = defaultdict(lambda: [0, 0])
    for j in joins:
        per_class[j["classId"]][1] += 1
        per_class[j["classId"]][0] += j["statusId"] in C.ACTIVE_STATUSES
    gs = [dict(snapshot_date=today, class_id=cid, direction=meta[cid]["direction"], grade=meta[cid]["grade"],
               active_joins=a, total_joins=t) for cid, (a, t) in per_class.items()]
    return fact, students, risk, mj, debts, gs


def load_names(mk, conn, user_ids) -> int:
    """ФИО учеников (только имя; телефоны и почты не берём). Догружаем только новых —
    ежедневный прогон не дёргает API по сотням учеников заново."""
    from sqlalchemy import select
    have = {r[0] for r in conn.execute(select(db.dim_students.c.user_id))}
    new = []
    for uid in sorted(set(user_ids) - have):
        try:
            name = mk.get(f"/company/users/{uid}").get("name")   # карточка без обёртки
        except Exception:
            continue   # не получилось — попробуем в следующий прогон
        if name:
            new.append(dict(user_id=uid, name=name.strip()))
    if new:
        conn.execute(db.dim_students.insert(), new)
    return len(new)


def main(force_snapshot=False):
    today = datetime.now(ZoneInfo(C.TZ)).date()
    mk = MoyKlass(C.MOYKLASS_API_KEY)
    dim, meta, joins, lessons, invoices, subs = extract(mk, today)
    fact, students, risk, mj, debts, gs = transform(meta, joins, lessons, invoices, subs, today)
    eng = db.get_engine(C.ANALYTICS_DATABASE_URL)
    db.md.create_all(eng)
    with eng.begin() as conn:
        db.replace_all(conn, db.dim_class, dim)
        db.replace_all(conn, db.fact_lesson, fact)
        db.replace_all(conn, db.mart_join, mj)
        db.replace_all(conn, db.mart_student_program, students)
        db.replace_all(conn, db.mart_churn_risk, risk)
        db.replace_all(conn, db.mart_movement, movement_rows(students, joins, meta, today))
        if today.weekday() == 0 or force_snapshot:   # понедельник
            db.replace_snapshot(conn, db.debt_snapshot, today, debts)
            db.replace_snapshot(conn, db.group_snapshot, today, gs)
        conn.execute(db.etl_run.insert(), [dict(finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
                     note=f"groups={len(dim)} joins={len(joins)} lessons={len(lessons)}")])
    ids = {s["user_id"] for s in students} | {d["user_id"] for d in debts}
    with eng.begin() as conn:
        added = load_names(mk, conn, ids)
        db.create_views(conn)
    print("имён добавлено:", added)
    print("OK", len(dim), "групп,", len(joins), "записей,", len(lessons), "занятий")


if __name__ == "__main__":
    main(force_snapshot="--snapshot" in sys.argv)
