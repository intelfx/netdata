# -*- coding: utf-8 -*-
# Description: sensors netdata python.d plugin
# Author: Pawel Krupa (paulfantom)
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os.path
import re
import subprocess
from collections import defaultdict
from enum import IntEnum
from fractions import Fraction
from numbers import Rational
from typing import (
    Optional,
    Callable,
)

import attrs

import bases.charts
from bases.FrameworkServices.SimpleService import SimpleService


class ErrorException(Exception):
    pass


class NoDataException(Exception):
    pass


class ChartType(IntEnum):
    TEMPERATURE = 1
    FAN = 2
    POWER = 3
    VOLTAGE = 4
    CURRENT = 5
    EFFICIENCY = 6
    TIME = 7


@attrs.define(kw_only=True, frozen=True)
class InputUnit:
    chart_type: ChartType
    name: str
    base_ratio: Optional[Rational] = None

    def get_base_ratio(self) -> Rational:
        if self.base_ratio is not None:
            return self.base_ratio
        return Fraction(1)

    @staticmethod
    def from_item(item: dict) -> 'InputUnit':
        unit_str = item['unit']
        try:
            unit = INPUT_UNIT_FROM_STR[unit_str]
        except KeyError:
            raise ErrorException(f'Unsupported: cannot determine unit for item {item}')
        return unit


@attrs.define(kw_only=True, frozen=True)
class ChartProto:
    type: ChartType
    name: str
    title: str
    unit_name: str
    store_ratio: Optional[Rational] = None
    limits: Optional[tuple[int, int]] = None
    skip_words: Optional[tuple[str, ...]] = None

    def get_store_ratio(self) -> Rational:
        if self.store_ratio is not None:
            return self.store_ratio
        return Fraction(1)

    def validate_limits(self, arg) -> bool:
        if self.limits is not None:
            return self.limits[0] <= arg <= self.limits[1]
        return True

    @staticmethod
    def from_item(item: dict) -> 'ChartProto':
        unit = InputUnit.from_item(item)
        return CHART_PROTO_FROM_TYPE[unit.chart_type]

    @staticmethod
    def from_unit(unit: InputUnit) -> 'ChartProto':
        return CHART_PROTO_FROM_TYPE[unit.chart_type]


INPUT_UNITS = [
    InputUnit(chart_type=ChartType.TEMPERATURE, name='°C'),
    InputUnit(chart_type=ChartType.FAN, name='rpm'),
    InputUnit(chart_type=ChartType.POWER, name='W'),
    InputUnit(chart_type=ChartType.VOLTAGE, name='V'),
    InputUnit(chart_type=ChartType.CURRENT, name='A'),
    InputUnit(chart_type=ChartType.EFFICIENCY, name='%'),
    InputUnit(chart_type=ChartType.TIME, name='s'),
]
INPUT_UNIT_FROM_STR = { x.name: x for x in INPUT_UNITS }

CHART_PROTO = [
    ChartProto(
        type=ChartType.TEMPERATURE,
        name='temperature',
        title='Temperature',
        unit_name='Celsius',
        store_ratio=Fraction(1000),
        limits=(-200, 200),
        skip_words=('temperature',)
    ),
    ChartProto(
        type=ChartType.FAN,
        name='fan',
        title='Fans speed',
        unit_name='Rotations/min',
        limits=(0, 10000),
        skip_words=('speed',)
    ),
    ChartProto(
        type=ChartType.POWER,
        name='power',
        title='Power',
        unit_name='Watt',
        store_ratio=Fraction(1000),
        limits=(0, 10000),
        skip_words=('power',)
    ),
    ChartProto(
        type=ChartType.VOLTAGE,
        name='voltage',
        title='Voltage',
        unit_name='Volt',
        store_ratio=Fraction(1000),
        limits=(0, 1000),
        skip_words=('voltage', 'rail')
    ),
    ChartProto(
        type=ChartType.CURRENT,
        name='current',
        title='Current',
        unit_name='Ampere',
        store_ratio=Fraction(1000),
        limits=(0, 1000),
        skip_words=('current',)
    ),
    ChartProto(
        type=ChartType.EFFICIENCY,
        name='efficiency',
        title='Efficiency',
        unit_name='Percent',
        store_ratio=Fraction(1000),
        limits=(0, 100),
        skip_words=('efficiency',)
    ),
    ChartProto(
        type=ChartType.TIME,
        name='uptime',
        title='Uptime',
        unit_name='seconds',
        store_ratio=None,
        limits=None,
    ),
]
CHART_PROTO_FROM_TYPE = { x.type: x for x in CHART_PROTO }


@attrs.define(kw_only=True, frozen=True)
class Device:
    id: str  # normalized unique string (e. g. "corsair-commander-pro-hidraw2")
    name: str  # normalized non-unique name (e. g. "corsair-commander-pro")
    label: str  # human-readable name (e. g. "corsair Commander Pro")
    bus: str  # raw (e. g. "hid")
    address: str  # raw (e. g. "/dev/hidraw2")


@attrs.define(kw_only=True, frozen=True)
class Chart:
    proto: ChartProto
    device: Device


@attrs.define(kw_only=True)
class ChartDataPoint:
    dim_id: str
    dim_label: str
    value: float


class ChartBuilder:
    data_points: dict[Chart, list[ChartDataPoint]]

    def __init__(self, service: 'Service'):
        self.service = service
        self.data_points = defaultdict(list)

    @staticmethod
    def make_chart_id(chart: Chart):
        return f'{chart.device.id}_{chart.proto.name}'

    @staticmethod
    def make_dim_id(chart: Chart, data_point: ChartDataPoint):
        return f'{chart.device.id}_{chart.proto.name}_{data_point.dim_id}'

    @staticmethod
    def make_chart(chart: Chart, data: list[ChartDataPoint]):
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
            'id': ChartBuilder.make_chart_id(chart),
            # 'name': f'{type}.{id}', overridden in Chart.__init__()
            'title': chart.proto.title,
            'units': chart.proto.unit_name,
            'family': chart.proto.name,  # basically "sidebar section name"
            'context': f'sensors.{chart.proto.name}',  # basically "sidebar section id", must match family
            'chart_type': 'line',
            'hidden': '',
        }

        chart_labels = {
            'sensor_id': chart.device.id,
            'sensor_name': chart.device.name,
            'sensor_bus': chart.device.bus,
            'sensor_address': chart.device.address,
        }

        chart_options_overrides = {
            # normally job_name(), override this
            'type': 'sensors',
            # normally {type}.{id}, fix this up as well
            'name': f'sensors.{chart_options["id"]}',
        }

        chart_lines = [{
            'id': ChartBuilder.make_dim_id(chart, data_point),
            'name': data_point.dim_label,
            'algorithm': 'absolute',
            'multiplier': chart.proto.get_store_ratio().denominator,
            'divisor': chart.proto.get_store_ratio().numerator,
            'hidden': '',
        } for data_point in data]

        return {
            'options': [ chart_options.get(key) for key in bases.charts.CHART_PARAMS[1:] ],
            'labels': chart_labels,
            'lines': [
                [ line.get(key) for key in bases.charts.DIMENSION_PARAMS ]
                for line in chart_lines
            ],
            'overrides': chart_options_overrides,
        }

    def submit(
        self,
        proto: ChartProto,
        device: Device,
        item_id: str,
        item_label: str,
        value: float,
    ):
        self.data_points[
            Chart(proto=proto, device=device)
        ].append(
            ChartDataPoint(dim_id=item_id, dim_label=item_label, value=value)
        )

    def make_chart_priority(self, proto: ChartProto):
        return self.service.priority + int(proto.type)

    def build_charts(self):
        for chart, data in self.data_points.items():
            chart_id = ChartBuilder.make_chart_id(chart)
            if chart_id in self.service.charts:
                continue

            chart_spec = ChartBuilder.make_chart(chart, data)
            netdata_chart = self.service.charts.add_chart(chart_spec['options'], labels=chart_spec['labels'])
            for dim in chart_spec['lines']:
                netdata_chart.add_dimension(dim)
            # update chart priority (cannot be set through add_chart())
            netdata_chart.params['priority'] = self.make_chart_priority(chart.proto)
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
    LIQUIDCTL = 'liquidctl'
    SUDO = 'sudo'

    def __init__(self, configuration=None, name=None):
        SimpleService.__init__(self, configuration=configuration, name=name)
        self.use_sudo = configuration.get('use_sudo', True)
        self.command = configuration.get('command', Service.LIQUIDCTL).split()
        self.sudo = configuration.get('sudo', Service.SUDO).split() if self.use_sudo else None
        self.order = list()
        self.definitions = dict()
        self.priority = 60000

    def _run_cmd(self, args):
        cmdline = list()
        if self.use_sudo:
            cmdline += self.sudo + [ '--' ]
        cmdline += self.command
        cmdline += args

        try:
            p = subprocess.run(cmdline, check=True, text=True,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            raise ErrorException(f'Failed to run {cmdline}: process returned {e.returncode}')
        except Exception as e:
            raise ErrorException(f'Failed to execute {cmdline}: {e}')

        return p.stdout

    @staticmethod
    def _normalize(arg: str, proto: ChartProto = None) -> str:
        r = arg.casefold()

        if proto is not None and proto.skip_words is not None:
            r = ' '.join([
                word
                for word in r.split()
                if word not in proto.skip_words
            ])

        r = re.sub(r'([a-z]+) ([0-9]+)', r'\1\2', r)
        r = re.sub(r'\+([0-9.]+v)', r'\1', r)
        r = re.sub(r'([0-9]+)\.([0-9]+)v', r'\1v\2', r)
        r = re.sub(r'[^a-z0-9]+', '-', r)
        return r

    def _get_data(self):
        input = json.loads(self._run_cmd(['status', '--json']))
        chart_builder = ChartBuilder(self)

        device_seen: dict[str, Device] = dict()
        for device_json in input:
            # build device metadata
            device_label = device_json["description"]
            device_name = self._normalize(device_label)
            device_id = device_name + '-' + os.path.basename(device_json["address"])
            device = Device(
                bus=device_json["bus"],
                address=device_json["address"],
                label=device_json["description"],
                name=device_name,
                id=device_id,
            )

            # see if we have duplicate ids
            assert device_id not in device_seen
            device_seen[device_id] = device

            # process device metrics (items)
            for item in device_json["status"]:
                # deduce metric type from its unit and find relevant chart prototype
                try:
                    item_unit = InputUnit.from_item(item)
                    chart_proto = ChartProto.from_unit(item_unit)
                except ErrorException as e:
                    self.warning(f'Skipping item: {e}')
                    continue

                # build item metadata
                item_label = item["key"]
                item_id = self._normalize(item_label, chart_proto)

                # build item value
                item_value = item["value"]
                if not chart_proto.validate_limits(item_value):
                    self.warning(f'Bad item value (expected within {chart_proto.limits[0]} and {chart_proto.limits[1]}), skipping: {item}')
                    continue

                # submit metric
                chart_builder.submit(
                    proto=chart_proto,
                    device=device,
                    item_id=item_id,
                    item_label=item_label,
                    value=item_value * item_unit.get_base_ratio(),
                )

        chart_builder.build_charts()
        return chart_builder.build_data()

    def get_data(self):
        try:
            return self._get_data()
        except NoDataException:
            return None
        except ErrorException as e:
            self.error(*e.args)
            return None
        except Exception as e:
            self.error(f'Failed to get data: {e}')
            return None

    def check(self):
        self.priority = self.charts.priority
        return bool(self.get_data() and self.charts)
