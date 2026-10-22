from datetime import date
import pytest
from classify import parse_grade, direction_of, refusal_type, build_student_programs, risk_rows

@pytest.mark.parametrize("name,grade", [
    ("Уч. год 26/27 - 6 кл ПН, ЧТ 16:00", 6), ("Уч. год 26/27 - 7-2 (ПН ЧТ 18:00)", 7),
    ("Уч. год 26/27 - 11 кл ПН, ЧТ 15:00", 11), ("Уч. год 26/27 - 7 кл СР 16.00, СБ 15:00 (дистант)", 7),
    ("Уч. год 26/27 - Школа+: углубленная математика (3 класс) ВС 11:50", 3),
    ("Уч. год 26/27 - 1 кл (ШС) ЧТ 12:20", 1), ("Уч. год 26/27 - 4 кл СР 18:20", 4)])
def test_grade(name, grade):
    assert parse_grade(name) == grade

def test_directions():
    assert direction_of("Уч. год 26/27 - Заниматика (5-летки) СБ 09:50", 115556, "Кружки для дошкольников") == ("olymp", 0)
    assert direction_of("Уч. год 26/27 - Школа+: углубленная математика (2 класс) ВС 10:00", 112069, "Кружки 2 класса") == ("school_plus", 2)
    assert direction_of("Уч. год 26/27 - 1 кл (ШС) ЧТ 12:20", 112047, "Кружки 1 класса") == ("olymp", 1)
    assert direction_of("Уч. год 26/27 - 5 кл ПН", 115554, "Кружки 5 класса") == ("olymp", 5)
    assert direction_of("Что-то", 136650, "Сборы") is None

@pytest.mark.parametrize("d,g,v,exp", [
    ("olymp", 3, 0, "no_show"), ("olymp", 3, 1, "after_trial"), ("olymp", 3, 2, "after_trial"),
    ("olymp", 3, 3, "after_month"), ("olymp", 3, 5, "after_month"), ("olymp", 3, 6, "late"),
    ("school_plus", 2, 5, "after_month"), ("school_plus", 2, 6, "late"), ("preschool", 0, 4, "after_month"),
    ("olymp", 5, 2, "after_trial"), ("olymp", 5, 3, "after_month"), ("olymp", 8, 9, "after_month"),
    ("olymp", 8, 10, "late"), ("olymp", 11, 0, "no_show")])
def test_refusal_type(d, g, v, exp):
    assert refusal_type(d, g, v) == exp

META = {1: dict(direction="olymp", grade=6), 2: dict(direction="olymp", grade=6)}
def J(i, user, cls, st, created="2026-09-01T10:00:00+00:00", changed="2026-10-20T10:00:00+00:00"):
    return dict(id=i, userId=user, classId=cls, statusId=st, createdAt=created, stateChangedAt=changed,
                statusChangeReasonId=445974)

def test_refusal_by_program_and_date_of_last_visit():
    # ходил в две группы подряд (4 + 3 посещения), в обеих отказ -> один отказ "после месяца" (7 <= 9)
    visits = {(10, "olymp"): [date(2026, 9, d) for d in (3, 5, 10, 12)] + [date(2026, 9, 24), date(2026, 9, 26), date(2026, 9, 28)]}
    rows = build_student_programs([J(1, 10, 1, 1), J(2, 10, 2, 1)], META, visits)
    assert len(rows) == 1
    r = rows[0]
    assert (r["status"], r["visits"], r["refusal_type"]) == ("refused", 7, "after_month")
    assert r["refusal_date"] == date(2026, 9, 28) and r["refusal_month"] == date(2026, 9, 1)  # месяц по последнему посещению

def test_moved_between_groups_is_not_refusal():
    rows = build_student_programs([J(1, 10, 1, 4), J(2, 10, 2, 2)], META, {})
    assert rows[0]["status"] == "active" and rows[0]["refusal_type"] is None
    rows = build_student_programs([J(1, 11, 1, 4)], META, {})
    assert rows[0]["status"] == "completed"

def test_no_show_date_falls_back_to_status_change():
    r = build_student_programs([J(1, 12, 1, 1, changed="2026-10-08T09:39:59+00:00")], META, {})[0]
    assert r["refusal_type"] == "no_show" and r["refusal_date"] == date(2026, 10, 8)

def test_not_attending_counts_as_active():
    assert build_student_programs([J(1, 13, 1, 82325)], META, {})[0]["status"] == "active"

def test_risk_young_vs_older():
    today = date(2026, 10, 22)
    st = [dict(user_id=1, direction="olymp", grade=3, status="active", visits=5, last_visit=None),
          dict(user_id=2, direction="olymp", grade=7, status="active", visits=5, last_visit=None),
          dict(user_id=3, direction="olymp", grade=7, status="active", visits=5, last_visit=None),
          dict(user_id=4, direction="olymp", grade=3, status="refused", visits=1, last_visit=None)]
    ab = {(1, "olymp"): [date(2026, 10, 19)],                      # младший: 1 пропуск -> риск
          (2, "olymp"): [date(2026, 10, 19)],                      # старший: 1 пропуск -> нет
          (3, "olymp"): [date(2026, 10, 19), date(2026, 10, 21)],  # старший: 2 -> риск
          (4, "olymp"): [date(2026, 10, 21)]}
    assert {r["user_id"] for r in risk_rows(st, ab, today)} == {1, 3}
    # пропуск старше 7 дней не считается
    assert risk_rows(st[:1], {(1, "olymp"): [date(2026, 10, 14)]}, today) == []


def test_refusal_before_classes_start_goes_to_september():
    """Записался на год заранее и отказался в мае -> no_show, месяц отказа = сентябрь;
    настоящая дата сохраняется в refusal_date."""
    meta = {1: dict(direction="olymp", grade=3)}
    joins = [dict(id=1, userId=7, classId=1, statusId=1, createdAt="2026-04-10T00:00:00+00:00",
                  stateChangedAt="2026-05-15T00:00:00+00:00")]
    r = build_student_programs(joins, meta, {})[0]
    assert (r["refusal_type"], r["refusal_date"], r["refusal_month"]) == \
           ("no_show", date(2026, 5, 15), date(2026, 9, 1))
    joins[0]["stateChangedAt"] = "2026-10-03T00:00:00+00:00"
    assert build_student_programs(joins, meta, {})[0]["refusal_month"] == date(2026, 10, 1)


def test_movement_by_month():
    from classify import movement_rows
    meta = {1: dict(direction="olymp", grade=3)}
    J = lambda i, uid, st, created, changed: dict(id=i, userId=uid, classId=1, statusId=st,
                                                 createdAt=created + "T00:00:00+00:00",
                                                 stateChangedAt=changed + "T00:00:00+00:00")
    joins = [J(1, 1, 2, "2026-05-10", "2026-05-10"),     # записан весной, учится
             J(2, 2, 1, "2026-09-02", "2026-09-20"),     # пришёл в сентябре, 1 посещение, отказ
             J(3, 3, 2, "2026-10-05", "2026-10-05"),     # пришёл в октябре
             J(4, 4, 4, "2026-09-01", "2026-10-12")]     # завершил/перешёл в октябре
    visits = {(2, "olymp"): [date(2026, 9, 10)], (4, "olymp"): [date(2026, 9, 8), date(2026, 10, 6)]}
    students = build_student_programs(joins, meta, visits)
    rows = {r["month"]: r for r in movement_rows(students, joins, meta, date(2026, 10, 22))}
    sep, octo = rows[date(2026, 9, 1)], rows[date(2026, 10, 1)]
    assert (sep["start_count"], sep["came"], sep["after_trial"], sep["end_count"]) == (0, 3, 1, 2)
    assert (octo["start_count"], octo["came"], octo["completed"], octo["end_count"]) == (2, 1, 1, 2)
    assert sep["end_count"] == octo["start_count"]
