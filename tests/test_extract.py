"""extract() против поддельного API в РЕАЛЬНОМ формате «Моего Класса» (проверено вживую):
courses/classes — голый массив без учёта limit, invoices — без фильтра по группе,
lessons — без фильтра по диапазону дат, users/{id} — карточка без обёртки."""
from datetime import date

import etl
from mk_client import MoyKlass

CID = 701506
CLASSES = [dict(id=CID, name="Уч. год 26/27 - 11 кл ПН, ЧТ 15:00", courseId=110848, status="opened"),
           dict(id=5, name="Уч. год 25/26 - 11 кл", courseId=110848, status="closed")] + \
          [dict(id=1000 + i, name=f"старая {i}", courseId=110848, status="closed") for i in range(600)]


class FakeMK(MoyKlass):
    def __init__(self):
        self.calls = []

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == "/company/courses":
            return [dict(id=110848, name="Кружки 10-11 классов")]
        if path == "/company/classes":
            return CLASSES                       # limit/offset игнорируются
        if path.startswith("/company/users/"):
            return dict(id=1, name=" Иванов Иван ")
        off, lim = params["offset"], params["limit"]
        if path == "/company/joins":
            items = [dict(id=11, userId=1, classId=params["classId"], statusId=2)]
        elif path == "/company/lessons":
            assert "date" not in params           # диапазон дат API не принимает
            items = [dict(id=i, classId=CID, date=d, status=1, records=[])
                     for i, d in enumerate(["2026-05-20", "2026-09-07", "2026-10-21", "2026-10-28"])]
        elif path == "/company/userSubscriptions":
            items = [dict(id=77, mainClassId=CID)]
        elif path == "/company/invoices":
            assert "classId" not in params        # такого фильтра у счетов нет
            items = [dict(id=i, userId=1, price=100, payed=0, userSubscriptionId=None, joinId=None)
                     for i in range(1200)]
        else:
            raise AssertionError(path)
        return {path.rsplit("/", 1)[1].replace("userSubscriptions", "subscriptions"): items[off:off + lim]}


def test_extract_real_api_shapes():
    mk = FakeMK()
    dim, meta, joins, lessons, invoices, subs = etl.extract(mk, date(2026, 10, 22))
    assert list(meta) == [CID]
    assert [L["date"] for L in lessons] == ["2026-09-07", "2026-10-21"]   # только сезон и до сегодня
    assert len(invoices) == 1200                                         # все страницы, один проход
    assert sum(p == "/company/invoices" for p, _ in mk.calls) == 3
    assert len(joins) == 1 and len(subs) == 1


def test_debt_by_join_id():
    """Счёт «единой суммой» привязан к записи (joinId), а не к абонементу."""
    meta = {CID: dict(direction="olymp", grade=11, name="x")}
    joins = [dict(id=11, userId=1, classId=CID, statusId=2, createdAt=None, stateChangedAt=None)]
    inv = [dict(id=9, userId=1, price=5000, payed=1000, payUntil=None, userSubscriptionId=None, joinId=11)]
    *_, debts, _ = etl.transform(meta, joins, [], inv, [], date(2026, 10, 22))
    assert [(d["invoice_id"], d["class_id"], d["debt"]) for d in debts] == [(9, CID, 4000)]


def test_load_names_reads_card_without_wrapper(tmp_path):
    import db
    eng = db.get_engine(f"sqlite:///{tmp_path}/t.db")
    db.md.create_all(eng)
    with eng.begin() as c:
        assert etl.load_names(FakeMK(), c, [1]) == 1
        assert c.execute(db.dim_students.select()).one().name == "Иванов Иван"
