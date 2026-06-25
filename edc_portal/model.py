from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EanMeasurement:
    ean: str
    before_kwh: float
    after_kwh: float
    missed_kwh: float = 0.0

    @property
    def shared_kwh(self) -> float:
        return max(0.0, self.before_kwh - self.after_kwh)


@dataclass
class Interval:
    start: datetime
    end: datetime
    producers: list[EanMeasurement]
    consumers: list[EanMeasurement]
    errors: list[str] = field(default_factory=list)

    @property
    def production_before_kwh(self) -> float:
        return sum(item.before_kwh for item in self.producers)

    @property
    def production_after_kwh(self) -> float:
        return sum(item.after_kwh for item in self.producers)

    @property
    def consumption_before_kwh(self) -> float:
        return sum(item.before_kwh for item in self.consumers)

    @property
    def consumption_after_kwh(self) -> float:
        return sum(item.after_kwh for item in self.consumers)

    @property
    def shared_kwh(self) -> float:
        producer_shared = self.production_before_kwh - self.production_after_kwh
        consumer_shared = self.consumption_before_kwh - self.consumption_after_kwh
        return max(0.0, min(producer_shared, consumer_shared))

    @property
    def missed_kwh(self) -> float:
        return min(self.production_after_kwh, self.consumption_after_kwh)


@dataclass
class ParsedReport:
    source_file: str
    producers: list[str]
    consumers: list[str]
    intervals: list[Interval]
