"""HROne Employee Attendance & Analytics API. Python 3.11+, FastAPI, PyMongo."""
import os, re, calendar
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Literal
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from bson import json_util
from datetime import date, datetime
from bson import ObjectId, Timestamp

load_dotenv()
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=2500, tz_aware=True, tzinfo=timezone.utc)
db = client[os.getenv("MONGO_DB", "attendance_db")]
IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
PRESENCE = {"PRESENT", "WFH", "ON_DUTY"}
STATUSES = PRESENCE | {"ABSENT", "LEAVE"}
app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def ensure_indexes():
    db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_employee_date")
    db.attendance_logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="attendance_date_emp")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("punch_in", DESCENDING)], name="attendance_emp_punchin")
    db.attendance_logs.create_index([("date", ASCENDING), ("late_minutes", ASCENDING)], name="attendance_date_late")
    db.employees.create_index([("department", ASCENDING), ("joined_on", ASCENDING)], name="employee_department_joined")
    db.employees.create_index([("joined_on", 1)],name="employee_joined_on")

def now_utc(): return datetime.now(UTC).replace(microsecond=0)
def trunc_seconds(dt: datetime) -> datetime:
    if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0)
def epoch_to_dt(value: Optional[int]) -> datetime:
    if value is None: return now_utc()
    if type(value) is not int or value < 100_000_000_000 or value > 4_102_444_800_000:
        raise HTTPException(422, "timestamps must be epoch milliseconds in the supported range")
    try: return datetime.fromtimestamp(value / 1000, UTC).replace(microsecond=0)
    except (OverflowError, OSError, ValueError): raise HTTPException(422, "invalid timestamp")
def dt_to_epoch(value):
    if value is None: return None
    if value.tzinfo is None: value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)
def round_half_up(value, places=2):
    if value is None: return None
    return float(Decimal(str(value)).quantize(Decimal("1") if places == 0 else Decimal("0." + "0"*(places-1) + "1"), rounding=ROUND_HALF_UP))
def parse_date(s: str) -> date:
    try:
        d = date.fromisoformat(s)
        if d.isoformat() != s: raise ValueError()
        return d
    except (ValueError, TypeError): raise HTTPException(422, "date must be YYYY-MM-DD")
def parse_month(s: str) -> tuple[date,date]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", s or ""): raise HTTPException(422, "month must be YYYY-MM")
    y,m = map(int,s.split("-")); last=calendar.monthrange(y,m)[1]
    return date(y,m,1), date(y,m,last)
def ist_dt(d: date, hm: str) -> datetime:
    h,m=map(int,hm.split(":")); return datetime.combine(d,time(h,m),IST).astimezone(UTC)
def attendance_day(punch: datetime, employee: dict) -> date:
    local=punch.astimezone(IST); d=local.date()
    if employee["shift_end"] <= employee["shift_start"] and local.strftime("%H:%M") < employee["shift_end"]: d -= timedelta(days=1)
    return d
def compute_late_minutes(punch: datetime, shift_start: str, attendance_date: str) -> int:
    start=ist_dt(parse_date(attendance_date),shift_start)
    seconds=int((punch-start).total_seconds())
    return seconds//60 if seconds > 600 else 0
def shift_end_dt(attendance_date: str, shift_start: str, shift_end: str) -> datetime:
    d=parse_date(attendance_date)
    if shift_end <= shift_start: d += timedelta(days=1)
    return ist_dt(d,shift_end)
def compute_work_hours(pin, pout):
    if pin is None or pout is None: return None
    return round_half_up(int((pout-pin).total_seconds())/3600,2)
def compute_overtime(pout, shift_start, shift_end, attendance_date):
    end=shift_end_dt(attendance_date,shift_start,shift_end)
    mins=int((pout-end).total_seconds())//60
    return mins if mins >= 30 else 0
def derive(pin,pout,emp,day,status):
    if status not in PRESENCE: return {"work_hours":None,"late_minutes":0,"overtime_minutes":0,"half_day":False}
    late=compute_late_minutes(pin,emp["shift_start"],day) if pin else 0
    hours=compute_work_hours(pin,pout) if pin and pout else None
    overtime=compute_overtime(pout,emp["shift_start"],emp["shift_end"],day) if pout else 0
    return {"work_hours":hours,"late_minutes":late,"overtime_minutes":overtime,"half_day": bool(hours is not None and hours < 4.50)}
def serialize_doc(doc):
    if not doc: return doc
    out={k:v for k,v in doc.items() if k != "_id"}
    for k in ("created_at","punch_in","punch_out"):
        if k in out: out[k]=dt_to_epoch(out[k])
    hist=[]
    for entry in out.get("history",[]) or []:
        e=dict(entry); e["at"]=dt_to_epoch(e.get("at")); changes={}
        for k,v in (e.get("changes") or {}).items():
            changes[k]={"from":dt_to_epoch(v.get("from")) if k in ("punch_in","punch_out") else v.get("from"), "to":dt_to_epoch(v.get("to")) if k in ("punch_in","punch_out") else v.get("to")}
        e["changes"]=changes; hist.append(e)
    if "history" in out: out["history"]=hist
    return out
def validate_pagination(page,page_size):
    if page < 1 or not 1 <= page_size <= 100: raise HTTPException(422,"page must be >= 1 and page_size must be between 1 and 100")
def is_workday(d): return d.weekday() < 5
def workdays(start: date,end: date):
    if end < start: return 0
    return sum(1 for i in range((end-start).days+1) if (start+timedelta(days=i)).weekday()<5)
def safe_round(value, places=2): return None if value is None else round_half_up(value,places)
def month_filter(month):
    start,end=parse_month(month); return f"{start.isoformat()}", f"{end.isoformat()}", start, end

class EmployeeIn(BaseModel):
    model_config=ConfigDict(extra="ignore")
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1,max_length=100)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(min_length=1,max_length=50)
    shift_start: str = Field(default="09:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_end: str = Field(default="18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    joined_on: str
    @field_validator("joined_on")
    @classmethod
    def valid_join_date(cls,v): parse_date(v); return v
    @model_validator(mode="after")
    def shifts_differ(self):
        if self.shift_start == self.shift_end: raise ValueError("shift_start must differ from shift_end")
        return self
class PunchInIn(BaseModel):
    model_config=ConfigDict(extra="ignore")
    emp_code: str
    punched_at: Optional[int] = Field(default=None, strict=True)
    status: Literal["PRESENT","WFH","ON_DUTY"] = "PRESENT"
    @field_validator("punched_at")
    @classmethod
    def valid_ts(cls,v):
        if v is not None and (type(v) is not int or not 100_000_000_000 <= v <= 4_102_444_800_000): raise ValueError("punched_at must be epoch milliseconds")
        return v
class PunchOutIn(BaseModel):
    model_config=ConfigDict(extra="ignore")
    emp_code: str
    punched_at: Optional[int] = Field(default=None, strict=True)
    @field_validator("punched_at")
    @classmethod
    def valid_ts(cls,v):
        if v is not None and (type(v) is not int or not 100_000_000_000 <= v <= 4_102_444_800_000): raise ValueError("punched_at must be epoch milliseconds")
        return v
class RegularizeIn(BaseModel):
    model_config=ConfigDict(extra="ignore")
    status: Optional[Literal["PRESENT","WFH","ON_DUTY","ABSENT","LEAVE"]] = None
    punch_in: Optional[int] = Field(default=None, strict=True)
    punch_out: Optional[int] = Field(default=None, strict=True)
    reason: str = Field(min_length=5,max_length=200)
    regularized_by: str = Field(min_length=1,max_length=50)
    @field_validator("punch_in","punch_out")
    @classmethod
    def valid_ts(cls,v):
        if v is not None and (type(v) is not int or not 100_000_000_000 <= v <= 4_102_444_800_000): raise ValueError("timestamps must be epoch milliseconds")
        return v

@app.get("/health")
def health():
    try: client.admin.command("ping"); return {"status":"ok"}
    except PyMongoError: raise HTTPException(503,"MongoDB unavailable")

@app.post("/employees",status_code=201)
def create_employee(body: EmployeeIn):
    doc=body.model_dump(); doc["created_at"]=now_utc()
    try: db.employees.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409,"emp_code already exists")
    return serialize_doc(doc)

@app.get("/employees")
def list_employees(department: Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    q={}
    if department is not None: q["department"]=department
    total=db.employees.count_documents(q)
    cur=db.employees.find(q,{"_id":0}).sort("emp_code",ASCENDING).skip((page-1)*page_size).limit(page_size)
    return {"items":[serialize_doc(x) for x in cur],"total":total,"page":page,"page_size":page_size}

@app.post("/attendance/punch-in",status_code=201)
def punch_in(body:PunchInIn):
    emp=db.employees.find_one({"emp_code":body.emp_code})
    if not emp: raise HTTPException(404,"employee not found")
    ts=epoch_to_dt(body.punched_at); day=attendance_day(ts,emp).isoformat()
    doc={"emp_code":body.emp_code,"date":day,"status":body.status,"punch_in":ts,"punch_out":None,"work_hours":None,"late_minutes":compute_late_minutes(ts,emp["shift_start"],day),"overtime_minutes":0,"half_day":False,"history":[]}
    try: db.attendance_logs.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409,"already punched in for this attendance date")
    return serialize_doc(doc)

@app.post("/attendance/punch-out")
def punch_out(body:PunchOutIn):
    emp=db.employees.find_one({"emp_code":body.emp_code})
    if not emp: raise HTTPException(404,"employee not found")
    ts=epoch_to_dt(body.punched_at)
    doc=db.attendance_logs.find_one({"emp_code":body.emp_code,"punch_in":{"$ne":None,"$lte":ts}},sort=[("punch_in",DESCENDING)])
    if not doc: raise HTTPException(404,"no punch-in found")
    if doc.get("punch_out") is not None: raise HTTPException(409,"record already punched out")
    if ts <= doc["punch_in"] or ts > doc["punch_in"]+timedelta(hours=24): raise HTTPException(422,"punch-out must be after punch-in and within 24 hours")
    derived=derive(doc["punch_in"],ts,emp,doc["date"],doc["status"])
    updated=db.attendance_logs.find_one_and_update({"_id":doc["_id"],"punch_out":None}, {"$set":{"punch_out":ts,**derived}},return_document=ReturnDocument.AFTER)
    if not updated: raise HTTPException(409,"record already punched out")
    return serialize_doc(updated)

@app.get("/attendance")
def list_attendance(emp_code:Optional[str]=None,date_from:Optional[str]=None,date_to:Optional[str]=None,status:Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    validate_pagination(page,page_size); q={}
    if emp_code is not None:q["emp_code"]=emp_code
    if date_from or date_to:
        q["date"]={}
        if date_from: parse_date(date_from); q["date"]["$gte"]=date_from
        if date_to: parse_date(date_to); q["date"]["$lte"]=date_to
        if date_from and date_to and date_from>date_to: raise HTTPException(422,"date_from must be <= date_to")
    if status is not None:
        if status not in STATUSES: raise HTTPException(422,"invalid status")
        q["status"]=status
    total=db.attendance_logs.count_documents(q)
    docs=db.attendance_logs.find(q,{"_id":0}).sort([("date",DESCENDING),("emp_code",ASCENDING)]).skip((page-1)*page_size).limit(page_size)
    return {"items":[serialize_doc(d) for d in docs],"total":total,"page":page,"page_size":page_size}

@app.patch("/attendance/{emp_code}/{date}")
def regularize(emp_code:str,date:str,body:RegularizeIn):
    parse_date(date); emp=db.employees.find_one({"emp_code":emp_code})
    if not emp: raise HTTPException(404,"employee not found")
    old=db.attendance_logs.find_one({"emp_code":emp_code,"date":date})
    if not old: raise HTTPException(404,"attendance record not found")
    status=body.status if body.status is not None else old["status"]
    pin=epoch_to_dt(body.punch_in) if body.punch_in is not None else old.get("punch_in")
    pout=epoch_to_dt(body.punch_out) if body.punch_out is not None else old.get("punch_out")
    if status in ("ABSENT","LEAVE"):
        if body.punch_in is not None or body.punch_out is not None: raise HTTPException(422,"ABSENT/LEAVE cannot include punch times")
        pin=pout=None
    else:
        if pin is None: raise HTTPException(422,"presence status requires punch_in")
        if attendance_day(pin,emp).isoformat()!=date: raise HTTPException(422,"punch_in must belong to the attendance date")
        if pout is not None and (pout<=pin or pout>pin+timedelta(hours=24)): raise HTTPException(422,"punch_out must be after punch_in and within 24 hours")
    derived=derive(pin,pout,emp,date,status)
    newvals={"status":status,"punch_in":pin,"punch_out":pout,**derived}
    keys=("status","punch_in","punch_out","work_hours","late_minutes","overtime_minutes","half_day")
    changes={}
    for k in keys:
        before=old.get(k, False if k=="half_day" else 0 if k in ("late_minutes","overtime_minutes") else None)
        after=newvals[k]
        if before != after: changes[k]={"from":before,"to":after}
    if not changes: raise HTTPException(422,"request does not change the record")
    entry={"at":now_utc(),"by":body.regularized_by,"reason":body.reason,"changes":changes}
    # Optimistic compare-and-set prevents concurrent edits from overwriting history.
    filt={"_id":old["_id"],"status":old["status"],"punch_in":old.get("punch_in"),"punch_out":old.get("punch_out"),"history":old.get("history",[])}
    updated=db.attendance_logs.find_one_and_update(filt,{"$set":newvals,"$push":{"history":entry}},return_document=ReturnDocument.AFTER)
    if not updated: raise HTTPException(409,"record changed concurrently; retry")
    return serialize_doc(updated)

@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code:str,month:str):
    emp=db.employees.find_one({"emp_code":emp_code})
    if not emp: raise HTTPException(404,"employee not found")
    start_s,end_s,start,end=month_filter(month)
    # Stored derived values are authoritative; aggregation only summarizes them.
    pipe=[{"$match":{"emp_code":emp_code,"date":{"$gte":start_s,"$lte":end_s}}},{"$group":{"_id":None,"present_days":{"$sum":{"$cond":[{"$and":[{"$in":["$status",list(PRESENCE)]},{"$gt":[{"$dayOfWeek":{"$dateFromString":{"dateString":"$date"}}},1]},{"$lt":[{"$dayOfWeek":{"$dateFromString":{"dateString":"$date"}}},7]}]},{"$cond":[{"$eq":[{"$ifNull":["$half_day",False]},True]},0.5,1]},0]}},"leave_days":{"$sum":{"$cond":[{"$eq":["$status","LEAVE"]},1,0]}},"late_count":{"$sum":{"$cond":[{"$gt":[{"$ifNull":["$late_minutes",0]},0]},1,0]}},"total_late_minutes":{"$sum":{"$ifNull":["$late_minutes",0]}},"total_overtime_minutes":{"$sum":{"$ifNull":["$overtime_minutes",0]}}}}]
    rows=list(db.attendance_logs.aggregate(pipe)); a=rows[0] if rows else {}
    wd=workdays(max(start,parse_date(emp["joined_on"])),end)
    present=safe_round(a.get("present_days",0),2)
    pct=safe_round(present/wd*100,4) if wd else None
    return {"emp_code":emp_code,"month":month,"working_days":wd,"present_days":present,"leave_days":a.get("leave_days",0),"late_count":a.get("late_count",0),"total_late_minutes":a.get("total_late_minutes",0),"total_overtime_minutes":a.get("total_overtime_minutes",0),"attendance_pct":pct}

@app.get("/analytics/departments/summary")
def department_summary(month:str,department:Optional[str]=None):
    start_s,end_s,start,end=month_filter(month)
    pipe=[{"$match":{"joined_on":{"$lte":end_s},**({"department":department} if department is not None else {})}},{"$lookup":{"from":"attendance_logs","let":{"code":"$emp_code"},"pipeline":[{"$match":{"$expr":{"$and":[{"$eq":["$emp_code","$$code"]},{"$gte":["$date",start_s]},{"$lte":["$date",end_s]}]}}}],"as":"logs"}},{"$unwind":{"path":"$logs","preserveNullAndEmptyArrays":True}},{"$group":{"_id":"$department","headcount":{"$addToSet":"$emp_code"},"present_days":{"$sum":{"$cond":[{"$in":["$logs.status",list(PRESENCE)]},{"$cond":[{"$eq":[{"$ifNull":["$logs.half_day",False]},True]},0.5,1]},0]}},"hours":{"$push":{"$cond":[{"$and":[{"$in":["$logs.status",list(PRESENCE)]},{"$ne":["$logs.work_hours",None]}]},"$logs.work_hours",None]}},"late_count":{"$sum":{"$cond":[{"$gt":[{"$ifNull":["$logs.late_minutes",0]},0]},1,0]}},"total_late_minutes":{"$sum":{"$ifNull":["$logs.late_minutes",0]}},"leave_count":{"$sum":{"$cond":[{"$eq":["$logs.status","LEAVE"]},1,0]}},"on_duty_count":{"$sum":{"$cond":[{"$eq":["$logs.status","ON_DUTY"]},1,0]}}}},{"$project":{"_id":0,"department":"$_id","headcount":{"$size":"$headcount"},"present_days":{"$round":["$present_days",2]},"avg_work_hours":{"$let":{"vars":{"valid":{"$filter":{"input":"$hours","as":"h","cond":{"$ne":["$$h",None]}}}},"in":{"$cond":[{"$gt":[{"$size":"$$valid"},0]},{"$round":[{"$avg":"$$valid"},2]},None]}}},"late_count":1,"total_late_minutes":1,"leave_count":1,"on_duty_count":1}},{"$sort":{"department":1}}]
    items=list(db.employees.aggregate(pipe,allowDiskUse=True))
    return {"month":month,"items":items}

@app.get("/analytics/leaderboard/late")
def late_leaderboard(month:str,limit:int=Query(10,ge=1,le=50),department:Optional[str]=None):
    start_s,end_s,_,_=month_filter(month)
    pipe=[{"$match":{"date":{"$gte":start_s,"$lte":end_s},"late_minutes":{"$gt":0}}},{"$group":{"_id":"$emp_code","total_late_minutes":{"$sum":"$late_minutes"},"late_count":{"$sum":1}}},{"$lookup":{"from":"employees","localField":"_id","foreignField":"emp_code","as":"employee"}},{"$unwind":"$employee"}]
    if department is not None: pipe.append({"$match":{"employee.department":department}})
    pipe += [{"$sort":{"total_late_minutes":-1,"_id":1}},{"$setWindowFields":{"sortBy":{"total_late_minutes":-1},"output":{"rank":{"$rank":{}}}}},{"$match":{"rank":{"$lte":limit}}},{"$project":{"_id":0,"rank":1,"emp_code":"$_id","name":"$employee.name","department":"$employee.department","total_late_minutes":1,"late_count":1}},{"$sort":{"total_late_minutes":-1,"emp_code":1}}]
    items=list(db.attendance_logs.aggregate(pipe,allowDiskUse=True))
    return {"month":month,"items":items}

@app.get("/analytics/departments/{department}/trend")
def department_trend(department:str,from_:str=Query(...,alias="from"),to:str=Query(...)):
    start=parse_date(from_); end=parse_date(to)
    if end<start or (end-start).days+1>92: raise HTTPException(422,"invalid date range: to must be >= from and range <= 92 days")
    if not db.employees.find_one({"department":department}): raise HTTPException(404,"department not found")
    # MongoDB generates every calendar day; no Python-side date loop. Join daily logs and compute window average.
    pipe=[{"$documents":[{"start":from_,"end":to,"department":department}]},{"$project":{"department":1,"dates":{"$map":{"input":{"$range":[0,{"$add":[{"$dateDiff":{"startDate":{"$dateFromString":{"dateString":"$start"}},"endDate":{"$dateFromString":{"dateString":"$end"}},"unit":"day"}},1]}]},"as":"n","in":{"$dateToString":{"date":{"$dateAdd":{"startDate":{"$dateFromString":{"dateString":"$start"}},"unit":"day","amount":"$$n"}},"format":"%Y-%m-%d"}}}}}},{"$unwind":"$dates"},{"$set":{"date":"$dates","is_working_day":{"$and":[{"$gt":[{"$dayOfWeek":{"$dateFromString":{"dateString":"$dates"}}},1]},{"$lt":[{"$dayOfWeek":{"$dateFromString":{"dateString":"$dates"}}},7]}]}}},{"$lookup":{"from":"employees","let":{"dept":"$department","day":"$date"},"pipeline":[{"$match":{"$expr":{"$and":[{"$eq":["$department","$$dept"]},{"$lte":["$joined_on","$$day"]}]}}},{"$project":{"_id":0,"emp_code":1}}],"as":"eligible"}},{"$set":{"headcount":{"$size":"$eligible"}}},{"$lookup":{"from":"attendance_logs","let":{"deptCodes":"$eligible.emp_code","day":"$date"},"pipeline":[{"$match":{"$expr":{"$and":[{"$eq":["$date","$$day"]},{"$in":["$emp_code","$$deptCodes"]}]}}},{"$group":{"_id":None,"present_count":{"$sum":{"$cond":[{"$and":[{"$in":["$status",list(PRESENCE)]},{"$gt":[{"$dayOfWeek":{"$dateFromString":{"dateString":"$date"}}},1]},{"$lt":[{"$dayOfWeek":{"$dateFromString":{"dateString":"$date"}}},7]}]},{"$cond":[{"$eq":[{"$ifNull":["$half_day",False]},True]},0.5,1]},0]}},"late_count":{"$sum":{"$cond":[{"$gt":[{"$ifNull":["$late_minutes",0]},0]},1,0]}}}}],"as":"daily"}},{"$set":{"present_count":{"$ifNull":[{"$arrayElemAt":["$daily.present_count",0]},0]},"late_count":{"$ifNull":[{"$arrayElemAt":["$daily.late_count",0]},0]}}},{"$set":{"attendance_rate":{"$cond":[{"$and":["$is_working_day",{"$gt":["$headcount",0]}]},{"$round":[{"$divide":["$present_count","$headcount"]},4]},None]}}},{"$sort":{"date":1}},{"$setWindowFields":{"sortBy":{"date":1},"output":{"moving_avg_7d":{"$avg":"$attendance_rate","window":{"documents":[-6,"current"]}}}}},{"$project":{"_id":0,"date":1,"is_working_day":1,"headcount":1,"present_count":{"$round":["$present_count",2]},"late_count":1,"attendance_rate":1,"moving_avg_7d":{"$cond":[{"$eq":["$moving_avg_7d",None]},None,{"$round":["$moving_avg_7d",4]}]}}}]
    items=list(db.command("aggregate",1,pipeline=pipe,cursor={}).get("cursor",{}).get("firstBatch",[]))
    return {"department":department,"items":items}


def make_json_safe(value):
    """Convert MongoDB explain output into JSON-compatible values."""
    if isinstance(value, Timestamp):
        return {"time": value.time, "increment": value.inc}

    if isinstance(value, ObjectId):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, bytes):
        return {"hex": value.hex()}

    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [make_json_safe(v) for v in value]

    return value


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(endpoint:str,emp_code:Optional[str]=None,month:Optional[str]=None,department:Optional[str]=None,limit:int=Query(10,ge=1,le=50),date_from:Optional[str]=None,date_to:Optional[str]=None,status:Optional[str]=None,from_:Optional[str]=Query(None,alias="from"),to:Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    allowed={"attendance_list","employee_monthly","department_summary","late_leaderboard","department_trend"}
    if endpoint not in allowed: raise HTTPException(422,"unknown endpoint")
    if endpoint=="attendance_list":
        q={}
        if emp_code is not None:q["emp_code"]=emp_code
        if date_from or date_to:
            q["date"]={}
            if date_from:parse_date(date_from);q["date"]["$gte"]=date_from
            if date_to:parse_date(date_to);q["date"]["$lte"]=date_to
        if status:q["status"]=status
        exp=db.command("explain",{"find":"attendance_logs","filter":q,"sort":{"date":-1,"emp_code":1},"skip":(page-1)*page_size,"limit":page_size},verbosity="executionStats"); coll="attendance_logs"
    elif endpoint=="employee_monthly":
        if not emp_code or not month: raise HTTPException(422,"emp_code and month are required")
        a,b,_,_=month_filter(month); pipe=[{"$match":{"emp_code":emp_code,"date":{"$gte":a,"$lte":b}}},{"$group":{"_id":"$emp_code","count":{"$sum":1}}}]
        exp=db.command("explain",{"aggregate":"attendance_logs","pipeline":pipe,"cursor":{}},verbosity="executionStats");coll="attendance_logs"
    elif endpoint=="department_summary":
        if not month:raise HTTPException(422,"month is required")
        a,b,_,_=month_filter(month); q={"joined_on":{"$lte":b}}
        if department is not None:q["department"]=department
        exp=db.command("explain",{"find":"employees","filter":q},verbosity="executionStats");coll="employees"
    elif endpoint=="late_leaderboard":
        if not month:raise HTTPException(422,"month is required")
        a,b,_,_=month_filter(month);pipe=[{"$match":{"date":{"$gte":a,"$lte":b},"late_minutes":{"$gt":0}}},{"$group":{"_id":"$emp_code","total":{"$sum":"$late_minutes"}}}]
        exp=db.command("explain",{"aggregate":"attendance_logs","pipeline":pipe,"cursor":{}},verbosity="executionStats");coll="attendance_logs"
    else:
        if not department or not from_ or not to:raise HTTPException(422,"department, from and to are required")
        parse_date(from_);parse_date(to)
        exp=db.command("explain",{"find":"employees","filter":{"department":department,"joined_on":{"$lte":to}}},verbosity="executionStats");coll="employees"
    return {"endpoint":endpoint,"collection":coll,"explain":make_json_safe(exp)}
