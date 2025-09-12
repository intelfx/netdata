import dataclasses
import re
import shlex
import subprocess
from collections import abc
from enum import IntEnum
from typing import (
    Optional,
)

from bases import dblc
from bases.dblc import (
    ErrorException,
    NoDataException,
    ChartType,
    ChartProto,
    Chart,
    ChartBuilder,
    DimProto,
    ChartInstance,
)


# This is prepended to all chart and dimension IDs.
PLUGIN_ID = 'zfsiostat'


@dataclasses.dataclass(kw_only=True)
class InfluxDataPoint:
    timestamp_ns: int
    name: str
    labels: dict[str, str]
    dimensions: dict[str, int|float]

    def get_dims(self, *keys: str, default=...) -> dict[str, int]:
        if default is ...:
            return { k: self.dimensions[k] for k in keys }
        else:
            return { k: self.dimensions.get(k, default) for k in keys }

    @staticmethod
    def _parse_label(item: str, sep: str, value: str) -> str:
        if sep != '=':
            raise ErrorException(f'Invalid InfluxDB label: {item!r}')
        return value

    @staticmethod
    def _parse_value(item: str, sep: str, value: str) -> int|float:
        if sep != '=':
            raise ErrorException(f'Invalid InfluxDB dimension: {item!r}')
        if value.endswith('u'):
            return int(value[:-1])
        elif '.' in value:
            return float(value)
        raise ErrorException(f'Unrecognized InfluxDB value: {value!r}')

    @classmethod
    def parse(cls, text: str) -> abc.Iterable['InfluxDataPoint']:
        for line in text.splitlines():
            parts = line.split(' ')
            if len(parts) != 3:
                raise ErrorException(f'Invalid InfluxDB line: {line!r}')

            timestamp_ns = int(parts[2])
            labels = parts[0].split(',')
            dims = parts[1].split(',')
            yield cls(
                timestamp_ns=timestamp_ns,
                name=labels[0],
                labels={
                    k: InfluxDataPoint._parse_label(item, sep, v)
                    for item, (k, sep, v)
                    in (
                        (l, l.partition('=')) for l in labels[1:]
                    )
                },
                dimensions={
                    k: InfluxDataPoint._parse_value(item, sep, v)
                    for item, (k, sep, v)
                    in (
                        (d, d.partition('=')) for d in dims
                    )
                }
            )


class DataType(IntEnum):
    AMOUNT = 1
    OPS = 3
    TIME = 4
    RATIO = 5


CHART_PROTO = [
    ChartProto(
        type=DataType.AMOUNT,
        representation=ChartType.GAUGE,
        name='capacity',
        title='Capacity',
        unit_name='bytes',
        dimensions=(
            DimProto(source='alloc', id='allocated', label='Allocated'),
            DimProto(source='free', id='free', label='Free'),
            DimProto(source='size', id='size', label='Capacity'),
        )
    ),
    ChartProto(
        type=DataType.RATIO,
        representation=ChartType.GAUGE,
        name='fragmentation',
        title='Fragmentation',
        unit_name='percent',
        # store_ratio=Fraction(1, 100),
        dimensions=(
            DimProto(source='fragmentation', id='total', label='Total'),
        )
    ),
    ChartProto(
        type=DataType.AMOUNT,
        representation=ChartType.COUNTER,
        name='bandwidth',
        title='Bandwidth',
        unit_name='bytes',
        dimensions=(
            DimProto(source='read_bytes', id='read', label='Read'),
            DimProto(source='write_bytes', id='write', label='Write'),
        )
    ),
    ChartProto(
        type=DataType.OPS,
        representation=ChartType.COUNTER,
        name='iops',
        title='I/O',
        unit_name='operations',
        dimensions=(
            DimProto(source='read_ops', id='read', label='Read'),
            DimProto(source='write_ops', id='write', label='Write'),
        )
    ),
    ChartProto(
        type=DataType.OPS,
        representation=ChartType.COUNTER,
        name='errors',
        title='Errors',
        unit_name='operations',
        dimensions=(
            DimProto(source='read_errors', id='read', label='Read'),
            DimProto(source='write_errors', id='write', label='Write'),
            DimProto(source='checksum_errors', id='checksum', label='Checksum'),
        )
    ),

    ChartProto(
        type=DataType.OPS,
        representation=ChartType.COUNTER | ChartType.HISTOGRAM,
        name='io_latency',
        title='I/O latency',
        unit_name='operations',
    ),

    ChartProto(
        type=DataType.OPS,
        representation=ChartType.COUNTER | ChartType.HISTOGRAM,
        name='io_size',
        title='I/O size',
        unit_name='bytes',
    ),

    ChartProto(
        type=DataType.OPS,
        representation=ChartType.GAUGE,
        name='queue_depth',
        title='Queue depth',
        unit_name='operations',
        dimensions=(
            DimProto(source='pending', id='pending', label='Pending'),
            DimProto(source='active', id='active', label='Active'),
        )
    ),

    # ChartProto(
    #     type=DataType.TIME,
    #     representation=ChartType.GAUGE,
    #     name='scan_elapsed',
    #     title='Scan time',
    #     unit_name='seconds',
    # ),
    #
    # ChartProto(
    #     type=DataType.TIME,
    #     representation=ChartType.GAUGE,
    #     name='scan_since',
    #     title='Since last scan',
    #     unit_name='seconds',
    # )
]
CHART_PROTO_FROM_NAME = { x.name: x for x in CHART_PROTO }
CHART_PROTO_ORDER = { id(x): idx for idx, x in enumerate(CHART_PROTO) }


@dataclasses.dataclass(kw_only=True, frozen=True)
class Device(dblc.Device):
    pool: str  # ZFS pool name
    vdev: str  # abstract ZFS vdev name (e.g., "root/raidz-0/disk0")
    path: Optional[str] = None  # path to the physical device node of a leaf vdev
    is_root: bool = False  # whether the vdev is a root vdev (@vdev == "root")
    is_leaf: bool = False  # whether the vdev is a leaf vdev (@path is not None)
    is_toplevel: bool = False  # whether the vdev is a "top-level" vdev

    def make_chart_family_suffix(self) -> str:
        if self.is_leaf:
            return f'(leaf)'
        elif self.is_toplevel:
            return f'(top-level)'
        elif self.is_root:
            return f'(root)'
        return None

    def make_chart_context_prefix(self) -> str:
        if self.is_leaf:
            return self.pool + '_leaf'
        elif self.is_toplevel:
            return self.pool + '_toplevel'
        elif self.is_root:
            return self.pool + '_root'
        return self.pool

    def make_chart_title_suffix(self) -> str:
        if self.is_leaf:
            return f'({self.pool} leaf)'
        elif self.is_toplevel:
            return f'({self.pool} top-level)'
        elif self.is_root:
            return f'({self.pool} root)'
        return f'({self.pool} misc)'

    def make_chart_id_prefix(self) -> str:
        # drop leading "root" unless that's the entire name (i.e., root vdev)
        vdev_escaped = re.sub(r'[^a-zA-Z0-9_-]', '_', self.vdev.removeprefix("root/"))
        return f'{self.pool}/{vdev_escaped}'

    def make_chart_id_title_suffix(self) -> Optional[str]:
        return f'({self.pool}/{self.vdev.removeprefix("root/")})'

    def make_chart_labels(self) -> dict[str, str]:
        labels = {
            'pool': self.pool,
            'vdev': self.vdev,
            'vdev_is_root': self.is_root,
            'vdev_is_toplevel': self.is_toplevel,
            'vdev_is_leaf': self.is_leaf,
        }
        if self.path is not None:
            labels['vdev_path'] = self.path
        return labels


class Service(dblc.Service):
    COMMAND = ['/usr/lib/zfs/zpool_influxdb']
    SUDO = 'sudo'

    def __init__(self, configuration=None, name=None):
        super().__init__(
            configuration=configuration,
            name=name,
            plugin_id=PLUGIN_ID,
        )
        self.use_sudo = configuration.get('use_sudo', True)
        self.command = Service._parse_cmd(
            configuration.get('command', Service.COMMAND)
        )
        self.sudo = Service._parse_cmd(
            configuration.get('sudo', Service.SUDO)
        ) if self.use_sudo else None
        self.zpools = configuration.get('zpools') or []

    def make_chart_priority(self, chart: Chart) -> int:
        return self.priority \
            + CHART_PROTO_ORDER[id(chart.proto)] * 4 \
            + (0 if chart.device.is_root else
               1 if chart.device.is_toplevel else
               2 if not chart.device.is_leaf else
               3)

    @staticmethod
    def _parse_cmd(cmd: str | list[str]) -> list[str]:
        if isinstance(cmd, str):
            return shlex.split(cmd)
        return cmd

    def _run_cmd(self, args):
        cmdline = []
        if self.use_sudo:
            cmdline += self.sudo + [ '--' ]
        cmdline += self.command
        cmdline += args

        try:
            p = subprocess.run(cmdline, check=True, text=True,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            raise ErrorException(f'Failed to run {cmdline}: process returned {e.returncode}') from e
        except Exception as e:
            raise ErrorException(f'Failed to execute {cmdline}: {e}') from e

        return p.stdout

    @staticmethod
    def _extract_dimensions(
            *,
            builder: ChartBuilder,
            point: InfluxDataPoint,
            proto: ChartProto,
            instance: Optional[ChartInstance] = None,
            device: Device,
    ):
        assert proto.dimensions is not None
        for dim in proto.dimensions:
            value = point.dimensions.get(dim.source)
            if value is None:
                continue
            builder.submit(
                proto=proto,
                instance=instance,
                device=device,
                item=dim,
                # value=proto.ctor(value),
                value=value,
            )

    def _get_data(self, *, check: bool):
        text = self._run_cmd([])
        data = InfluxDataPoint.parse(text)
        chart_builder = ChartBuilder(self)

        data = list(data)

        for point in data:
            pool = point.labels.pop('name')
            vdev = point.labels.pop('vdev', 'root')
            vdev_path = point.labels.pop('path', None)
            device = Device(
                pool=pool,
                vdev=vdev,
                path=vdev_path,
                is_root=vdev == 'root',
                is_leaf=vdev_path is not None,
                is_toplevel=vdev.count('/') == 1,
            )

            def _extract(*, proto: ChartProto, instance: Optional[ChartInstance]):
                Service._extract_dimensions(
                    builder=chart_builder,
                    point=point,
                    proto=proto,
                    instance=instance,
                    device=device,
                )

            if point.name == 'zpool_stats':
                assert point.labels.keys() == {'state'}
                instance = ChartInstance(
                    labels=point.labels,
                )

                alloc_stats = point.get_dims('alloc', 'free', 'size')
                if any(v != 0 for v in alloc_stats.values()):
                    _extract(proto=CHART_PROTO_FROM_NAME['capacity'], instance=instance)
                # FIXME: fragmentation seems to only be valid for "top-level" vdevs (i.e., not
                #        mirror/stripe children, and not the root vdev). I'm not sure if the above
                #        condition is valid in all cases and possible topologies, so for now replace
                #        the "top-level" condition with a check whether alloc/free/size are nonzero.
                #        This should exclude mirror/stripe children (vdevs which are not allocation
                #        targets). Additionally, exclude the root vdev, because internally its
                #        fragmentation is not reported by libzfs even if its alloc/free/size are
                #        nonzero. What we see in `zpool status` is computed by the CLI, presumably
                #        as an average of some sort.
                if not device.is_root and any(v != 0 for v in alloc_stats.values()):
                    _extract(proto=CHART_PROTO_FROM_NAME['fragmentation'], instance=instance)

                _extract(proto=CHART_PROTO_FROM_NAME['bandwidth'], instance=instance)
                _extract(proto=CHART_PROTO_FROM_NAME['iops'], instance=instance)
                _extract(proto=CHART_PROTO_FROM_NAME['errors'], instance=instance)

                # TODO: add dimensions to illustrate the pool state
                #       (e.g. ONLINE, DEGRADED, OFFLINE, etc.)
                #       Extract it from the `state` label and transform it
                #       into a set of dimensions for each possible state
                #       (with the active state as `1` and others as `0`).
                #       This mimics what the default netdata zfs collector does.

            elif point.name == 'zpool_vdev_stats':
                # This entry duplicates zpool_vdev_queue, so ignore it.
                pass

            elif point.name == 'zpool_vdev_queue':
                proto = CHART_PROTO_FROM_NAME['queue_depth']

                for key, value in point.dimensions.items():
                    if m := re.match(r'^(sync|async)_(r|w|scrub|rebuild)_(active|pend)$', key):
                        kind = m.group(1)
                        io = {
                            'r': 'read',
                            'w': 'write',
                        }.get(m.group(2), m.group(2))
                        queue_type = {
                            'pend': 'pending',
                        }.get(m.group(3), m.group(3))
                    elif m:= re.match(r'^rebuild_(active|pend)$', key):
                        kind = 'rebuild'
                        io = 'write'
                        queue_type = {
                            'pend': 'pending',
                        }.get(m.group(1), m.group(1))
                    else:
                        raise ErrorException(f'Unrecognized metric: {point.name=!r}, {key=!r}')

                    instance = ChartInstance(
                        id=f'{kind}_{io}',
                        context=f'{kind}_{io}',
                        title=f'({kind} {io})',
                        labels={
                            'kind': kind,
                            'io': io,
                        }
                    )

                    chart_builder.submit(
                        proto=proto,
                        instance=instance,
                        device=device,
                        item=next(d for d in proto.dimensions if d.source == queue_type),
                        value=value,
                    )

            elif point.name == 'zpool_scan_stats':
                function = point.labels.pop('function')
                state = point.labels.pop('state')

                assert state in ('none', 'scanning', 'finished', 'canceled')
                # "errorscrub" exists in zfs.h, but not in zpool_influxdb; here for completeness
                # "scan" == unknown ("errorscrub" will be represented as "scan" unless
                # zpool_influxdb is updated)
                assert function in ('none_requested', 'scan', 'scrub', 'resilver', 'errorscrub')

                if function == 'none_requested':
                    continue

                if state == 'none':
                    continue

                # TODO: handle this

            elif point.name == 'zpool_latency':
                bucket = point.labels.pop('le')
                assert point.labels.keys() == set()

                def format_duration(seconds: float) -> str:
                    if seconds == float('+inf'):
                        return "infinity"
                    elif seconds >= 1:
                        return f"{int(seconds)}s"
                    elif seconds >= 1e-3:
                        return f"{int(seconds * 1e3)}ms"
                    elif seconds >= 1e-6:
                        return f"{int(seconds * 1e6)}us"
                    else:
                        return f"{int(seconds * 1e9)}ns"

                bucket_sec = float(bucket)
                bucket_id = f"{int(bucket_sec * 1e9)}ns" if bucket_sec != float("+inf") else "infinity"
                bucket_label = format_duration(bucket_sec)

                proto = CHART_PROTO_FROM_NAME['io_latency']
                for key, value in point.dimensions.items():
                    if m := re.match(r'^(total|disk|sync|async)_(read|write)$', key):
                        kind, io = m.group(1), m.group(2)
                    elif key == 'scrub':
                        kind, io = key, 'read'
                    elif key in ('trim', 'rebuild'):
                        kind, io = key, 'write'
                    else:
                        raise ErrorException(f'Unrecognized metric: {point.name=!r}, {key=!r}')

                    instance = ChartInstance(
                        id=f'{kind}_{io}',
                        context=f'{kind}_{io}',
                        title=f'({kind} {io})',
                        labels={
                            'kind': kind,
                            'io': io,
                        }
                    )
                    chart_builder.submit(
                        proto=proto,
                        instance=instance,
                        device=device,
                        item=DimProto(
                            source=key,
                            id=bucket_id,
                            label=bucket_label,
                        ),
                        value=value,
                    )

            elif point.name == 'zpool_io_size':
                bucket = point.labels.pop('le')
                assert point.labels.keys() == set()

                def format_bytes(bytes_: float) -> str:
                    if bytes_ == float("+inf"):
                        return "infinity"

                    units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB']

                    for u in units:
                        if bytes_ < 1024:
                            break
                        bytes_ /= 1024

                    return f"{int(bytes_)}{u}"

                bucket_bytes = float(bucket)
                bucket_id = f"{int(bucket_bytes)}B" if bucket_bytes != float("+inf") else "infinity"
                bucket_label = format_bytes(bucket_bytes)

                proto = CHART_PROTO_FROM_NAME['io_size']
                for key, value in point.dimensions.items():
                    if m := re.match(
                            r'^(sync|async|scrub|trim|rebuild)_(read|write)_(ind|agg)$', key):
                        kind, io, queue_type = m.group(1), m.group(2), m.group(3)
                        queue_type = {
                            'ind': 'individual',
                            'agg': 'aggregated',
                        }[queue_type]
                    else:
                        raise ErrorException(f'Unrecognized metric: {point.name=!r}, {key=!r}')

                    instance = ChartInstance(
                        id=f'{kind}_{io}_{queue_type}',
                        context=f'{kind}_{io}_{queue_type}',
                        title=f'({kind} {io} {queue_type})',
                        labels={
                            'kind': kind,
                            'io': io,
                            'queue_type': queue_type,
                        }
                    )
                    chart_builder.submit(
                        proto=proto,
                        instance=instance,
                        device=device,
                        item=DimProto(
                            source=key,
                            id=bucket_id,
                            label=bucket_label,
                        ),
                        value=value,
                    )

        chart_builder.build_charts()
        return chart_builder.build_data()

    def get_data(self):
        try:
            return self._get_data(check=False)
        except NoDataException:
            return None
        except ErrorException as e:
            self.error(*e.args)
            return None
        except Exception as e:
            self.error(f'Failed to get data: {e}')
            return None

    def check(self):
        try:
            return bool(self._get_data(check=True) and self.charts)
        except ErrorException as e:
            self.error(*e.args)
            return None
        except Exception as e:
            self.error(f'Failed to get data: {e}')
            return None
        except:
            return None
