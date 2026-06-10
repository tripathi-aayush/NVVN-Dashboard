from enum import Enum
from typing import Dict, List, Optional
from ninja import Schema
from datetime import date
from pydantic import Field

# class StateShortEnum(str, Enum):
#     "Short code = value, full name = key"

#     DL = "Delhi"
#     MH = "Maharashtra"
#     TN = "Tamil Nadu"
#     UP = "Uttar Pradesh"
#     AP = "Andhra Pradesh"
#     AR = "Arunachal Pradesh"
#     AS = "Assam"
#     BR = "Bihar"
#     CH = "Chandigarh"
#     CG = "Chhattisgarh"
#     GA = "Goa"
#     GJ = "Gujarat"
#     HR = "Haryana"
#     HP = "Himachal Pradesh"
#     JK = "J & K"
#     JH = "Jharkhand"
#     KA = "Karnataka"
#     KL = "Kerala"
#     MN = "Manipur"
#     ML = "Meghalaya"
#     MZ = "Mizoram"
#     MP = "Madhya Pradesh"
#     NL = "Nagaland"
#     OD = "Odisha"
#     PY = "Pondicherry"
#     PB = "Punjab"
#     RJ = "Rajasthan"
#     SK = "Sikkim"
#     TS = "Telangana"
#     TR = "Tripura"
#     UK = "Uttarakhand"
#     WB = "West Bengal"






#ye wala h original
# class StateShortEnum(str, Enum):
#     DL = "DL"
#     MH = "MH"
#     TN = "TN"
#     UP = "UP"
#     AP = "AP"
#     AR = "AR"
#     AS = "AS"
#     BR = "BR"
#     CH = "CH"
#     CG = "CG"
#     GA = "GA"
#     GJ = "GJ"
#     HR = "HR"
#     HP = "HP"
#     JK = "JK"
#     JH = "JH"
#     KA = "KA"
#     KL = "KL"
#     MN = "MN"
#     ML = "ML"
#     MZ = "MZ"
#     MP = "MP"
#     NL = "NL"
#     OD = "OD"
#     PY = "PY"
#     PB = "PB"
#     RJ = "RJ"
#     SK = "SK"
#     TS = "TS"
#     TR = "TR"
#     UK = "UK"
#     WB = "WB"




from enum import Enum

class StateShortEnum(str, Enum):
    DL  = "DL"
    AP  = "AP"
    ACP = "ACP"
    ASM = "ASM"
    BHR = "BHR"
    CHG = "CHG"
    CTG = "CTG"
    DNH = "DNH"
    DND = "DND"
    GOA = "GOA"
    GJT = "GJT"
    HRN = "HRN"
    HP  = "HP"
    JAK = "JAK"
    JHK = "JHK"
    KRT = "KRT"
    KRL = "KRL"
    MPD = "MPD"
    MHA = "MHA"
    MIP = "MIP"
    MGA = "MGA"
    MZM = "MZM"
    NGD = "NGD"
    ODI = "ODI"
    PU  = "PU"
    PNB = "PNB"
    RJ  = "RJ"
    SKM = "SKM"
    TND = "TND"
    TLG = "TLG"
    TPA = "TPA"
    UP  = "UP"
    UTK = "UTK"
    BGL = "BGL"







class StateOut(Schema):
    code: str
    name: str




class DateQuerySchema(Schema):
    forecast_date: date = Field(
        default_factory=date.today(),
        description="Date in YYYY-MM-DD format",
        example=date.today()
    )



class HourlyPointSchema(Schema):
    datetime: str
    mw: float
    temperature: float




class ForecastHourlyOut(Schema):
    state: str
    date: str
    season: str
    weekday: str
    is_weekend: bool
    is_holiday: bool
    energy_consumption_mu_per_day: float
    average_load_mw: float
    peak_load_mw: float
    mape_difference_percent: Optional[float] = None
    points: list[HourlyPointSchema]








class Forecast15MinPoint(Schema):
    datetime: str
    mw: float

class Forecast15MinOut(Schema):
    state: str
    date: str
    points: List[Forecast15MinPoint]





class TemperatureHourly(Schema):
    time: str
    temp: float

class TemperatureOut(Schema):
    state: str
    date: str
    average_temperature: float
    hourly: list[TemperatureHourly]




class PreviousPredictionItem(Schema):
    state: str
    date: str
    load_mw: float

class PreviousPredictionOut(Schema):
    count: int
    results: List[PreviousPredictionItem]



class MeritStateCurrentOut(Schema):
    Demand: Optional[str] = None
    ISGS: Optional[str] = None
    ImportData: Optional[str] = None


class DailyForecastPoint(Schema):
    date: str
    peak_load_mw: float
    average_load_mw: float
    min_load_mw: float
    energy_consumption_mu_per_day: float

class Forecast7DayOut(Schema):
    state: str
    start_date: str
    days: List[DailyForecastPoint]

class HistoricalDataPoint(Schema):
    date: str
    peak_load_mw: float
    average_load_mw: float
    min_load_mw: float

class HistoricalDataOut(Schema):
    state: str
    days: List[HistoricalDataPoint]

class AccuracyPoint(Schema):
    date: str
    actual_load_mw: float
    predicted_load_mw: float
    mape_percent: float

class AccuracyCheckOut(Schema):
    state: str
    overall_mape_percent: float
    points: List[AccuracyPoint]
