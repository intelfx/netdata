import dataclasses
import enum
import queue
import time
from collections import defaultdict
from fractions import Fraction
from numbers import Rational
from typing import (
    Optional,
    Callable,
    Any,
)

import bases.charts
from bases.FrameworkServices.SimpleService import SimpleService

class PeekableQueue[T](queue.Queue[T]):
    def unget(self, item: T, block=True, timeout=None):
        """Put an item at the front of the queue.

        If optional args 'block' is true and 'timeout' is None (the default),
        block if necessary until a free slot is available. If 'timeout' is
        a non-negative number, it blocks at most 'timeout' seconds and raises
        the Full exception if no free slot was available within that time.
        Otherwise ('block' is false), put an item on the queue if a free slot
        is immediately available, else raise the Full exception ('timeout' is
        ignored in that case).

        Raises ShutDown if the queue has been shut down.
        """
        with self.not_full:
            if self.is_shutdown:
                raise queue.ShutDown
            if self.maxsize > 0:
                if not block:
                    if self._qsize() >= self.maxsize:
                        raise queue.Full
                elif timeout is None:
                    while self._qsize() >= self.maxsize:
                        self.not_full.wait()
                        if self.is_shutdown:
                            raise queue.ShutDown
                elif timeout < 0:
                    raise ValueError("'timeout' must be a non-negative number")
                else:
                    endtime = time.monotonic() + timeout
                    while self._qsize() >= self.maxsize:
                        remaining = endtime - time.monotonic()
                        if remaining <= 0.0:
                            raise queue.Full
                        self.not_full.wait(remaining)
                        if self.is_shutdown:
                            raise queue.ShutDown
            self.queue.appendleft(item)
            self.unfinished_tasks += 1
            self.not_empty.notify()

    def peek(self, block=True, timeout=None) -> T:
        """Return an item from the queue without removing it.

        If optional args 'block' is true and 'timeout' is None (the default),
        block if necessary until an item is available. If 'timeout' is
        a non-negative number, it blocks at most 'timeout' seconds and raises
        the Empty exception if no item was available within that time.
        Otherwise ('block' is false), return an item if one is immediately
        available, else raise the Empty exception ('timeout' is ignored
        in that case).

        Raises ShutDown if the queue has been shut down and is empty,
        or if the queue has been shut down immediately.
        """
        with self.not_empty:
            if self.is_shutdown and not self._qsize():
                raise queue.ShutDown
            if not block:
                if not self._qsize():
                    raise queue.Empty
            elif timeout is None:
                while not self._qsize():
                    self.not_empty.wait()
                    if self.is_shutdown and not self._qsize():
                        raise queue.ShutDown
            elif timeout < 0:
                raise ValueError("'timeout' must be a non-negative number")
            else:
                endtime = time.monotonic() + timeout
                while not self._qsize():
                    remaining = endtime - time.monotonic()
                    if remaining <= 0.0:
                        raise queue.Empty
                    self.not_empty.wait(remaining)
                    if self.is_shutdown and not self._qsize():
                        raise queue.ShutDown
            return self.queue[0]


class ErrorException(Exception):
    pass


class NoDataException(Exception):
    pass


class Device:
    def make_dim_id(self) -> Optional[str]:
        """
        Returns a string to be used as part of the dimension identifier when a dimension is created
        per device (DimProto.per_device=True).
        """
        raise NotImplementedError

    def make_dim_label(self) -> Optional[str]:
        """
        Returns a string to be used as part of the dimension label when a dimension is created
        per device (DimProto.per_device=True).
        """
        raise NotImplementedError

    def make_chart_family_suffix(self) -> Optional[str]:
        """
        Returns a string that groups "charts" (time series) with the same ChartProto, but different
        Devices into "families" (sections in the UI).
        If this is None, all time series with the same ChartProto will be grouped into one family.
        """
        raise NotImplementedError

    def make_chart_context_prefix(self) -> Optional[str]:
        """
        Returns a string that groups "charts" (time series) with the same ChartProto, but different
        Devices into "contexts" (actual charts).
        If this is None, all time series with the same ChartProto will be grouped into one chart.
        """
        raise NotImplementedError

    def make_chart_title_suffix(self) -> Optional[str]:
        """
        Returns a string which is appended to the title of each "context" (actual chart).
        The results of this function should form the same equivalence classes as
        make_chart_context_prefix().
        """
        raise NotImplementedError

    def make_chart_id_prefix(self) -> Optional[str]:
        """
        Returns a string that groups data points with the same ChartProto, but different Devices
        into "charts" (time series).
        If this is None, all data points with the same ChartProto will be grouped into one time
        series (and will be unable to have distinct labels).
        """
        raise NotImplementedError

    def make_chart_labels(self) -> dict[str, str]:
        """
        Returns a dict of labels that should be associated with each "chart" (time series)
        for this Device.
        The results of this function should form the same equivalence classes as
        make_chart_id_prefix().
        """
        raise NotImplementedError


class ChartType(enum.IntFlag):
    GAUGE = 0
    COUNTER = enum.auto()
    HISTOGRAM = enum.auto()


@dataclasses.dataclass(kw_only=True, frozen=True)
class InputUnit:
    type: Any
    name: str
    base_ratio: Optional[Rational] = None

    def get_base_ratio(self) -> Rational:
        if self.base_ratio is not None:
            return self.base_ratio
        return Fraction(1)


@dataclasses.dataclass(kw_only=True, frozen=True)
class DimProto:
    source: str
    id: Optional[str]
    label: Optional[str]
    per_device: bool = False


@dataclasses.dataclass(kw_only=True, frozen=True)
class ChartProto:
    type: Any
    representation: ChartType
    name: str
    title: str
    unit_name: str

    ctor: Callable[[str], Any] = int
    store_ratio: Optional[Rational] = None

    # "sidebar section name"
    family_name: Optional[str] = None
    # "sidebar section id", ends up as {service}.{context_name}
    # "chart group", all charts with the same context name are rendered as a single chart in the UI
    context_name: Optional[str] = None

    dimensions: Optional[tuple[DimProto, ...]] = None

    def get_store_ratio(self) -> Rational:
        if self.store_ratio is not None:
            return self.store_ratio
        return Fraction(1)


@dataclasses.dataclass(kw_only=True, frozen=True)
class ChartInstance:
    id: Optional[str] = None
    context: Optional[str] = None
    title: Optional[str] = None
    family: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    """NOTE: labels must not be modified (this structure is used as a key)"""

    def __hash__(self):
        # Python does not have frozendict; sunrise by hand
        return hash((
            self.id,
            self.context,
            self.title,
            self.family,
            tuple(self.labels.items()) if self.labels is not None else None,
        ))


@dataclasses.dataclass(kw_only=True, frozen=True)
class Chart:
    proto: ChartProto
    instance: Optional[ChartInstance] = None
    device: Device

    def make_chart_family(self) -> str:
        return ' '.join(x for x in (
            self.proto.family_name or self.proto.title,
            self.instance.family if self.instance is not None else None,
            self.device.make_chart_family_suffix(),
        ) if x is not None)

    def make_chart_context(self) -> str:
        return '_'.join(x for x in (
            self.device.make_chart_context_prefix(),
            self.instance.context if self.instance is not None else None,
            self.proto.context_name or self.proto.name,
        ) if x is not None)

    def make_chart_title(self) -> str:
        return ' '.join(x for x in (
            self.proto.title,
            self.instance.title if self.instance is not None else None,
            self.device.make_chart_title_suffix(),
        ) if x is not None)

    def make_chart_id(self) -> str:
        return '_'.join(x for x in (
            self.device.make_chart_id_prefix(),
            self.instance.id if self.instance is not None else None,
            self.proto.name,
        ) if x is not None)

    def make_chart_labels(self) -> dict[str, str]:
        labels = self.device.make_chart_labels()
        if self.instance is not None and self.instance.labels is not None:
            labels.update(self.instance.labels)
        return labels


@dataclasses.dataclass(kw_only=True, frozen=True)
class ChartDataPoint:
    dim_proto: DimProto
    value: int | float


class ChartBuilder:
    data_points: dict[Chart, list[ChartDataPoint]]

    def __init__(self, service: 'Service'):
        self.service = service
        self.data_points = defaultdict(list)

    @staticmethod
    def make_dim_id(chart: Chart, data_point: ChartDataPoint):
        return '_'.join(x for x in (
            chart.make_chart_id(),
            chart.device.make_dim_id() if data_point.dim_proto.per_device else None,
            data_point.dim_proto.id,
        ) if x is not None)

    @staticmethod
    def make_dim_label(chart: Chart, data_point: ChartDataPoint):
        return ' '.join(x for x in (
            chart.device.make_dim_label() if data_point.dim_proto.per_device else None,
            data_point.dim_proto.label,
        ) if x is not None)

    def make_chart(self, chart: Chart, data: list[ChartDataPoint]):
        """
        # type == job_name(), implicitly prepended in Service.charts.add_chart()
        # name == {type}.{id}, implicitly overridden in Service.charts.add_chart() -> Chart.__init__()
        CHART_PARAMS = ['type', 'id', 'name', 'title', 'units', 'family', 'context', 'chart_type', 'hidden']
        DIMENSION_PARAMS = ['id', 'name', 'algorithm', 'multiplier', 'divisor', 'hidden']
        VARIABLE_PARAMS = ['id', 'value']

        CHART_TYPES = ['line', 'area', 'stacked']
        DIMENSION_ALGORITHMS = ['absolute', 'incremental', 'percentage-of-absolute-row', 'percentage-of-incremental-row']
        """

        chart_options = {
            # 'type': job_name(), added in Service.charts.add_chart()
            'id': chart.make_chart_id(),
            # 'name': f'{type}.{id}', overridden in Chart.__init__()
            'units': chart.proto.unit_name,
            'chart_type': 'line',
            'hidden': '',
            'title': chart.make_chart_title(),
            'context': f'{self.service.plugin_id}.{chart.make_chart_context()}',
            'family': chart.make_chart_family(),
        }

        chart_options_overrides = {
            # normally job_name(), override this
            'type': f'{self.service.plugin_id}',
            # normally {type}.{id}, fix this up as well
            'name': f'{self.service.plugin_id}.{chart_options["id"]}',
            # normally this can be set in chart_options, but "heatmap" is not accepted there
            'chart_type': 'heatmap' if chart.proto.representation & ChartType.HISTOGRAM else 'line',
        }

        chart_lines = [{
            'id': ChartBuilder.make_dim_id(chart, data_point),
            'name': ChartBuilder.make_dim_label(chart, data_point),
            'algorithm':
                'incremental' if chart.proto.representation & ChartType.COUNTER else 'absolute',
            'multiplier': chart.proto.get_store_ratio().denominator,
            'divisor': chart.proto.get_store_ratio().numerator,
            'hidden': '',
        } for data_point in data]

        return {
            'options': [ chart_options.get(key) for key in bases.charts.CHART_PARAMS[1:] ],
            'labels': chart.make_chart_labels(),
            'lines': [
                [ line.get(key) for key in bases.charts.DIMENSION_PARAMS ]
                for line in chart_lines
            ],
            'overrides': chart_options_overrides,
        }

    def submit(
            self,
            *,
            proto: ChartProto,
            instance: Optional[ChartInstance] = None,
            device: Device,
            item: DimProto,
            value: int | float,
    ):
        self.data_points[
            Chart(proto=proto, instance=instance, device=device)
        ].append(
            ChartDataPoint(dim_proto=item, value=value)
        )

    def build_charts(self):
        for chart, data in self.data_points.items():
            chart_id = chart.make_chart_id()
            if chart_id in self.service.charts:
                continue

            chart_spec = self.make_chart(chart, data)
            netdata_chart = self.service.charts.add_chart(
                chart_spec['options'],
                labels=chart_spec['labels'],
            )
            assert chart_id == netdata_chart.id

            for dim in chart_spec['lines']:
                netdata_chart.add_dimension(dim)
            # update chart priority (cannot be set through add_chart())
            netdata_chart.params['priority'] = self.service.make_chart_priority(chart)
            # update chart type and name (cannot be set through add_chart())
            netdata_chart.params.update(chart_spec['overrides'])

    def build_data(self) -> Optional[dict[str, int]]:
        return {
            ChartBuilder.make_dim_id(chart, data_point):
                int(data_point.value * chart.proto.get_store_ratio())
            for chart, data in self.data_points.items()
            for data_point in data
        } or None


class Service(SimpleService):
    priority: int
    # This is prepended to all chart and dimension IDs and chart contexts.
    # Append a trailing number here to use as a disambiguator during development.
    # Increment when chart definitions / structure changes to force netdata to create new charts.
    # Otherwise, the UI will show a combination of old and new charts.
    plugin_id: str

    def __init__(self, configuration, name, plugin_id: str):
        SimpleService.__init__(self, configuration=configuration, name=name)
        self.priority = self.charts.priority  # remember initial priority as we assign it ourselves
        self.plugin_id = plugin_id


    def make_chart_priority(self, chart: Chart) -> int:
        # chart priority in Netdata is a scalar, not a tuple, so we essentially
        # need to map this polynomial to a monotonic integer
        return self.priority
