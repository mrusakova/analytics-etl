"""Чистая бизнес-логика: направления, классы, типы отказов, риск оттока.
Без обращений к сети и БД — легко тестируется."""
import re
from collections import defaultdict
from datetime import date, datetime

import config as C

PRESCHOOL_COURSE_ID = 115556  # "Кружки для дошкольников"


def parse_grade(name: str, course_name: str | None = None) -> int | None:
    s = re.sub(r"Уч\.?\s*год\s*\d\d/\d\d\s*-?\s*", "", name or "", flags=re.I).strip()
    for pat in (r"^(\d{1,2})\s*кл", r"\((\d{1,2})\s*класс", r"^(\d{1,2})-\d\b", r"\b(\d{1,2})\s*кл\b"):
        m = re.search(pat, s)
        if m:
            return int(m.group(1))
    if course_name:
        m = re.search(r"Кружки\s+(\d{1,2})\s*класс", course_name)
        if m:
            return int(m.group(1))
    return None


def direction_of(class_name: str, course_id: int, course_name: str) -> tuple[str, int | None] | None:
    """-> (направление, класс) или None, если группа не из наших программ.
    Направления: olymp (Олимпиадная математика, вкл. «ШС» и дошкольников «Заниматика» как 0 класс),
    school_plus."""
    if course_id == PRESCHOOL_COURSE_ID or "дошкол" in (course_name or "").lower() \
            or "заниматика" in (class_name or "").lower():
        return "olymp", 0   # дошкольники = Олимпиадная математика, 0 класс
    if "Кружки" not in (course_name or ""):
        return None
    if "школа+" in (class_name or "").lower():
        return "school_plus", parse_grade(class_name, course_name)
    return "olymp", parse_grade(class_name, course_name)


def is_young(direction: str, grade: int | None) -> bool:
    return direction in ("preschool", "school_plus") or (grade is not None and grade <= 4)


def refusal_type(direction: str, grade: int | None, visits: int) -> str:
    trial_max, month_max = C.THRESH_YOUNG if is_young(direction, grade) else C.THRESH_OLDER
    if visits == 0:
        return "no_show"          # записался, но не дошёл
    if visits <= trial_max:
        return "after_trial"      # отказ после пробного
    if visits <= month_max:
        return "after_month"      # отказ после месяца
    return "late"                 # поздний отказ


def _d(s: str | None) -> date | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date() if s else None


def build_student_programs(joins, class_meta, visit_dates):
    """Одна строка = ученик x направление.
    joins: записи из API; class_meta: {classId: {direction, grade}};
    visit_dates: {(userId, direction): [date, ...]} — даты фактических посещений."""
    groups = defaultdict(list)
    for j in joins:
        meta = class_meta.get(j["classId"])
        if meta:
            groups[(j["userId"], meta["direction"])].append(j)
    rows = []
    for (uid, direction), js in groups.items():
        js.sort(key=lambda j: j["createdAt"])
        grade = class_meta[js[-1]["classId"]]["grade"]
        dates = sorted(visit_dates.get((uid, direction), []))
        visits = len(dates)
        statuses = {j["statusId"] for j in js}
        refused_js = [j for j in js if j["statusId"] == C.ST_REFUSED]
        if statuses & C.ACTIVE_STATUSES:
            status = "active"
        elif refused_js:
            status = "refused"
        else:
            status = "completed"   # завершил / перешёл — это не отказ
        r_type = r_date = reason = None
        if status == "refused":
            r_type = refusal_type(direction, grade, visits)
            r_date = dates[-1] if dates else max(_d(j["stateChangedAt"]) for j in refused_js)
            reason = max(refused_js, key=lambda j: j["stateChangedAt"]).get("statusChangeReasonId")
        rows.append(dict(
            user_id=uid, direction=direction, grade=grade, status=status, visits=visits,
            first_visit=dates[0] if dates else None, last_visit=dates[-1] if dates else None,
            joined_at=_d(js[0]["createdAt"]), refusal_type=r_type, refusal_date=r_date,
            refusal_month=refusal_month(r_date), reason_id=reason,
            groups_count=len(js)))
    return rows


def refusal_month(r_date: date | None) -> date | None:
    """Месяц отказа для графиков; отказы до начала занятий — в месяц начала (сентябрь)."""
    if not r_date:
        return None
    return max(r_date, date.fromisoformat(C.CLASSES_START)).replace(day=1)


def absences_in_window(absence_dates, today: date, window=C.RISK_WINDOW_DAYS):
    return sum(1 for d in absence_dates if 0 <= (today - d).days < window)


def risk_rows(students, absences_by_user_dir, today: date):
    """Подозрение на отток: активные ученики с пропусками за последние 7 дней."""
    out = []
    for s in students:
        if s["status"] != "active":
            continue
        n = absences_in_window(absences_by_user_dir.get((s["user_id"], s["direction"]), []), today)
        need = C.RISK_ABSENCES_YOUNG if is_young(s["direction"], s["grade"]) else C.RISK_ABSENCES_OLDER
        if n >= need:
            out.append(dict(user_id=s["user_id"], direction=s["direction"], grade=s["grade"],
                            absences_7d=n, visits=s["visits"], last_visit=s["last_visit"]))
    return out


REFUSAL_TYPES = ("no_show", "after_trial", "after_month", "late")


def _add_month(m: date) -> date:
    return date(m.year + (m.month == 12), m.month % 12 + 1, 1)


def movement_rows(students, joins, class_meta, today: date):
    """Движение контингента по месяцам: ученик x направление -> строки (месяц, направление, класс).
    На начало + пришли - ушли (по типам отказа + завершили/перешли) = на конец.
    Даты раньше начала занятий (записались/отказались весной) относим к месяцу начала занятий."""
    start = date.fromisoformat(C.CLASSES_START)
    done_date = defaultdict(lambda: None)   # дата «Завершил / перешёл» по ученику x направлению
    for j in joins:
        m = class_meta.get(j["classId"])
        if m and j["statusId"] == C.ST_DONE_OR_MOVED and j.get("stateChangedAt"):
            key, d = (j["userId"], m["direction"]), _d(j["stateChangedAt"])
            done_date[key] = max(filter(None, (done_date[key], d)))
    people = []   # (direction, grade, дата прихода, дата ухода, тип ухода)
    for s in students:
        if not s["joined_at"]:
            continue
        out, kind = None, None
        if s["status"] == "refused":
            out, kind = s["refusal_date"], s["refusal_type"]
        elif s["status"] == "completed":
            out, kind = done_date[(s["user_id"], s["direction"])] or s["last_visit"], "completed"
        came = max(s["joined_at"], start)
        if out:
            out = max(out, came)
        people.append((s["direction"], s["grade"], came, out, kind))
    rows = []
    month, last = start.replace(day=1), today.replace(day=1)
    while month <= last:
        nxt = _add_month(month)
        acc = defaultdict(lambda: dict.fromkeys(("start_count", "came", *REFUSAL_TYPES, "completed"), 0))
        for direction, grade, came, out, kind in people:
            a = acc[(direction, grade)]
            if came < month and (out is None or out >= month):
                a["start_count"] += 1
            if month <= came < nxt:
                a["came"] += 1
            if out and month <= out < nxt:
                a[kind] += 1
        for (direction, grade), a in acc.items():
            left = sum(a[k] for k in (*REFUSAL_TYPES, "completed"))
            if a["start_count"] or a["came"] or left:
                rows.append(dict(month=month, direction=direction, grade=grade, **a,
                                 left_count=left, end_count=a["start_count"] + a["came"] - left))
        month = nxt
    return rows
