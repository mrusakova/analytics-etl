from datetime import date
from sqlalchemy import select
import db
from etl import transform

TODAY = date(2026, 10, 22)
META = {701506: dict(direction="olymp", grade=11, name="Уч. год 26/27 - 11 кл ПН, ЧТ 15:00")}

def rec(uid, visit, good=False, summa=1400):
    return dict(id=uid * 10, userId=uid, visit=visit, goodReason=good, free=False, test=False,
                bill={"summa": summa} if summa else None)

def test_transform_and_load(tmp_path):
    lessons = [
        dict(id=1, date="2026-10-19", classId=701506, status=1,
             records=[rec(1, True), rec(2, False), rec(3, False, good=True)]),
        dict(id=2, date="2026-10-21", classId=701506, status=1, records=[rec(1, True), rec(2, False)]),
        dict(id=3, date="2026-10-24", classId=701506, status=0, records=[rec(1, False, summa=0)]),  # будущее
        dict(id=4, date="2026-10-20", classId=701506, status=1, records=[rec(1, False)]),             # не отмечено
    ]
    joins = [dict(id=i, userId=i, classId=701506, statusId=2, createdAt="2026-09-01T00:00:00+00:00",
                  stateChangedAt="2026-09-03T00:00:00+00:00") for i in (1, 2, 3)]
    invoices = [dict(id=9, userId=1, price=9600, payed=2000, payUntil="2026-10-10", userSubscriptionId=77),
                dict(id=10, userId=2, price=9600, payed=9600, payUntil="2026-10-10", userSubscriptionId=78)]
    subs = [dict(id=77, mainClassId=701506), dict(id=78, mainClassId=701506)]
    fact, students, risk, mj, debts, gs = transform(META, joins, [l for l in lessons], invoices, subs, TODAY)
    f = {r["lesson_id"]: r for r in fact}
    assert (f[1]["visits"], f[1]["absences"], f[1]["absences_good_reason"], f[1]["revenue"]) == (1, 1, 1, 4200)
    assert f[3]["conducted"] is False and f[3]["visits"] == 0
    assert f[4]["marked"] is False and f[4]["absences"] == 0   # неотмеченное занятие не даёт "пропусков"
    # ученик 2: пропуски 19 и 21 октября (2 шт.), 11 класс -> риск; ученик 3: уважительный -> нет
    assert {r["user_id"] for r in risk} == {2}
    assert [(d["invoice_id"], d["debt"], d["overdue"]) for d in debts] == [(9, 7600, True)]
    assert gs[0]["active_joins"] == 3

    eng = db.get_engine(f"sqlite:///{tmp_path}/t.db")
    db.md.create_all(eng)
    with eng.begin() as c:
        db.replace_all(c, db.fact_lesson, fact)
        db.replace_all(c, db.mart_student_program, students)
        db.replace_snapshot(c, db.debt_snapshot, TODAY, debts)
        db.replace_snapshot(c, db.debt_snapshot, TODAY, debts)   # повторный прогон в тот же день не дублирует
    with eng.connect() as c:
        assert len(c.execute(select(db.debt_snapshot)).all()) == 1
        assert len(c.execute(select(db.fact_lesson)).all()) == 4
