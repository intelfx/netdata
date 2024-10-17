# -*- coding: utf-8 -*-
# Description: sensors netdata python.d plugin
# Author: Pawel Krupa (paulfantom)
# SPDX-License-Identifier: GPL-3.0-or-later

from collections import defaultdict

from bases.FrameworkServices.SimpleService import SimpleService
from third_party import lm_sensors as sensors

ORDER = [
    'temperature',
    'fan',
    'power',
    'voltage',
    'energy',
    'current',
    'humidity',
]

# This is a prototype of chart definition which is used to dynamically create self.definitions
CHARTS = {
    'temperature': {
        'options': [None, 'Temperature', 'Celsius', 'temperature', 'sensors.temperature', 'line'],
        'lines': [
            [None, None, 'absolute', 1, 1000]
        ]
    },
    'voltage': {
        'options': [None, 'Voltage', 'Volts', 'voltage', 'sensors.voltage', 'line'],
        'lines': [
            [None, None, 'absolute', 1, 1000]
        ]
    },
    'current': {
        'options': [None, 'Current', 'Ampere', 'current', 'sensors.current', 'line'],
        'lines': [
            [None, None, 'absolute', 1, 1000]
        ]
    },
    'power': {
        'options': [None, 'Power', 'Watt', 'power', 'sensors.power', 'line'],
        'lines': [
            [None, None, 'absolute', 1, 1000]
        ]
    },
    'fan': {
        'options': [None, 'Fans speed', 'Rotations/min', 'fans', 'sensors.fan', 'line'],
        'lines': [
            [None, None, 'absolute', 1, 1000]
        ]
    },
    'energy': {
        'options': [None, 'Energy', 'Joule', 'energy', 'sensors.energy', 'line'],
        'lines': [
            [None, None, 'incremental', 1, 1000]
        ]
    },
    'humidity': {
        'options': [None, 'Humidity', 'Percent', 'humidity', 'sensors.humidity', 'line'],
        'lines': [
            [None, None, 'absolute', 1, 1000]
        ]
    }
}

LIMITS = {
    'temperature': [-127, 1000],
    'voltage': [-400, 400],
    'current': [-127, 127],
    'fan': [0, 65535]
}

SKIP_WORDS = {
    'temperature': ('temperature', 'temp'),
    'fan': ('speed',),
    'power': ('power',),
    'voltage': ('voltage', 'rail'),
    'current': ('current',),
}

TYPE_MAP = {
    0: 'voltage',
    1: 'fan',
    2: 'temperature',
    3: 'power',
    4: 'energy',
    5: 'current',
    6: 'humidity',
    # 7: 'max_main',
    # 16: 'vid',
    # 17: 'intrusion',
    # 18: 'max_other',
    # 24: 'beep_enable'
}

def _cleanup(feat_name: str, feat_type: str) -> str:
    r = feat_name

    skip_words = SKIP_WORDS.get(feat_type)
    if skip_words is not None:
        r = ' '.join([
            word
            for word in r.split()
            if word.casefold() not in skip_words
        ])
    return r

class Service(SimpleService):
    def __init__(self, configuration=None, name=None):
        SimpleService.__init__(self, configuration=configuration, name=name)
        self.order = list()
        self.definitions = dict()
        self.chips = configuration.get('chips')
        self.priority = 60000

    def get_data(self):
        seen: dict[str, dict[str, list]] = dict()
        data: dict[str, int] = dict()
        meta: dict[str, dict[str, str]] = dict()
        try:
            for chip in sensors.ChipIterator():
                chip_name = sensors.chip_snprintf_name(chip)
                seen[chip_name] = defaultdict(list)

                # split chip_name by hand
                chip_prefix = chip.prefix.decode('utf-8')
                chip_address = chip_name.removeprefix(chip_prefix + '-')
                assert chip_name != chip_address
                chip_bus = chip_address.split('-', maxsplit=1)[0]
                meta[chip_name] = {
                    'name': chip_name,
                    'prefix': chip_prefix,
                    'address': chip_address,
                    'bus': chip_bus,
                }

                for feat in sensors.FeatureIterator(chip):
                    if feat.type not in TYPE_MAP:
                        continue

                    feat_type = TYPE_MAP[feat.type]
                    feat_name = str(feat.name.decode())
                    feat_label = _cleanup(sensors.get_label(chip, feat), feat_type)
                    feat_limits = LIMITS.get(feat_type)
                    sub_feat = next(sensors.SubFeatureIterator(chip, feat))  # current value

                    if not sub_feat:
                        continue

                    try:
                        v = sensors.get_value(chip, sub_feat.number)
                    except sensors.SensorsError:
                        continue

                    if v is None:
                        continue

                    seen[chip_name][feat_type].append((feat_name, feat_label))

                    if feat_limits and (v < feat_limits[0] or v > feat_limits[1]):
                        continue

                    data[chip_name + '_' + feat_name] = int(v * 1000)

        except sensors.SensorsError as error:
            self.error(error)
            return None

        self.update_sensors_charts(seen, meta)

        return data or None

    def update_sensors_charts(self, seen, meta):
        for chip_name, feat in seen.items():
            if self.chips and not any([chip_name.startswith(ex) for ex in self.chips]):
                continue

            for feat_type, sub_feat in feat.items():
                if feat_type not in ORDER or feat_type not in CHARTS:
                    continue

                chart_id = '{}_{}'.format(chip_name, feat_type)
                if chart_id in self.charts:
                    continue

                chip_meta = meta[chip_name]
                chip_labels = {
                    'sensor_id': chip_meta['name'],
                    'sensor_name': chip_meta['prefix'],
                    'sensor_bus': chip_meta['bus'],
                    'sensor_address': chip_meta['address'],
                }

                params = [chart_id] + list(CHARTS[feat_type]['options'])
                new_chart = self.charts.add_chart(params, labels=chip_labels)
                new_chart.params['priority'] = self.get_chart_priority(feat_type)

                for name, label in sub_feat:
                    lines = list(CHARTS[feat_type]['lines'][0])
                    lines[0] = chip_name + '_' + name
                    lines[1] = label
                    new_chart.add_dimension(lines)

    def check(self):
        try:
            sensors.init()
        except sensors.SensorsError as error:
            self.error(error)
            return False

        self.priority = self.charts.priority

        return bool(self.get_data() and self.charts)

    def get_chart_priority(self, feat_type):
        for i, v in enumerate(ORDER):
            if v == feat_type:
                return self.priority + i
        return self.priority
