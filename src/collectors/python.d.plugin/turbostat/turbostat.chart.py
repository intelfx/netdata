import dataclasses
import enum
import functools
import itertools
import os.path
import queue
import sys
import shlex
import subprocess
import signal
import threading
import time
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import (
    Self,
    Optional,
    Iterable,
)

from bases import dblc
from bases.dblc import (
    PeekableQueue,
    ErrorException,
    NoDataException,
    ChartType,
    ChartProto,
    Chart,
    ChartBuilder,
    DimProto,
)


PLUGIN_ID = 'turbostat'

NSEC_PER_SEC = int(1e9)
NSEC_PER_MS = int(1e6)

_SHUTDOWN_QUEUE = PeekableQueue()
_SHUTDOWN_QUEUE.shutdown()


@dataclasses.dataclass(kw_only=True)
class TurbostatRawLine:
    timestamp_ns: int
    text: str

@dataclasses.dataclass(kw_only=True)
class TurbostatLine:
    items: dict[str, Optional[str]]

@dataclasses.dataclass(kw_only=True)
class TurbostatMeasurement:
    timestamp_ns: int
    fields: list[str]
    totals: TurbostatLine
    cpus: dict[int, TurbostatLine]

@dataclasses.dataclass(kw_only=True)
class TurbostatAccumulator:
    totals: defaultdict[str, int]
    cpus: defaultdict[int, defaultdict[str, int]]

    @classmethod
    def make(cls):
        return cls(totals=defaultdict(int), cpus=defaultdict(lambda: defaultdict(int)))

class Turbostat:
    service: dblc.Service
    command: list[str]
    reader_thread: Optional[threading.Thread]
    subprocess: Optional[subprocess.Popen]
    stdout_queue: PeekableQueue[TurbostatRawLine]
    rc_queue: PeekableQueue[int]
    header: list[str]
    accumulator: TurbostatAccumulator

    def __init__(self, command: list[str], *, service: dblc.Service):
        self.service = service
        self.command = command
        self.reader_thread = None
        self.subprocess = None
        self.stdout_queue = _SHUTDOWN_QUEUE
        self.rc_queue = _SHUTDOWN_QUEUE
        self.header = []
        self.accumulator = TurbostatAccumulator.make()

    def __enter__(self):
        self.run()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def run(self):
        if self.reader_thread is None:
            self.service.info(f"Starting turbostat: {self.command!r}")
            self.subprocess = subprocess.Popen(
                args=self.command,
                text=True,
                bufsize=1,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
            )
            self.stdout_queue = PeekableQueue()
            self.rc_queue = PeekableQueue()
            self.header = []
            self.accumulator = TurbostatAccumulator.make()
            self.reader_thread = threading.Thread(target=self._communicate, daemon=True)
            self.reader_thread.start()
            self._process_header()

    def stop(self):
        if self.reader_thread is not None:
            if self.subprocess.returncode is None:
                self.service.info(f"Stopping turbostat: PID {self.subprocess.pid}")
                self.subprocess.send_signal(signal.SIGINT)
            self.reader_thread.join()
            self.reader_thread = None
            self.subprocess = None
            rc = self.rc_queue.get(block=False)
            if rc != 0:
                raise ErrorException(f"{self.command!r} exited with non-zero status {rc}")
        return None

    def _communicate(self):
        with self.subprocess:
            while True:
                line: str = self.subprocess.stdout.readline()
                if not line:
                    break
                self.stdout_queue.put(
                    TurbostatRawLine(timestamp_ns=time.time_ns(), text=line.rstrip())
                )
        self.stdout_queue.shutdown()
        self.rc_queue.put(self.subprocess.wait())
        self.rc_queue.shutdown()

    def _process_header(self):
        while True:
            try:
                line = self.stdout_queue.get(timeout=0.1)
                self.header.append(line.text)
            except queue.Empty:
                break

    def measure(self, *, check: bool) -> list[TurbostatMeasurement]:
        ret = []

        # turbostat ends the current measurement interval and outputs the next round of statistics
        # on receipt of SIGUSR1. We use this mechanism (along with a very large "normal" interval)
        # to synchronize turbostat measurement period with Netdata's internal polling.
        if not check:
            # However, on initial check, we start turbostat with a reasonable interval and wait for
            # the measurement period to elapse normally.
            self.subprocess.send_signal(signal.SIGUSR1)

        # Process at least one measurement, then keep going while the subprocess queue is not empty
        ret.append(self._measure())
        while True:
            try:
                ret.append(self._measure(block=False))
            except (queue.Empty, queue.ShutDown):
                break
        return ret

    def _accumulate(self, measurement: TurbostatMeasurement):
        """
        Turbostat's metrics are all differential, which is not optimal, but most of them are
        normalized over time, which means we can submit them as gauges, which works.
        However, several metrics (like IRQ counts) are not normalized and instead reported as raw
        deltas from the previous measurement. This means we get different values depending on how
        fast Netdata polls us. We cannot report these metrics as gauges (e.g., "interrupts/sec"),
        so instead re-accumulate the deltas and then report them as counters.
        """
        def _accumulate_line(target: defaultdict[str, int], line: TurbostatLine):
            for key in ['IRQ', 'NMI', 'SMI']:
                if (value := line.items.get(key)) is not None:
                    value = int(value)
                    target[key] += value
                    line.items[key] = str(target[key])

        _accumulate_line(self.accumulator.totals, measurement.totals)
        for idx, line in measurement.cpus.items():
            _accumulate_line(self.accumulator.cpus[idx], line)

    def _measure(self, **kwargs) -> TurbostatMeasurement:
        """
        Read one measurement consisting of a single header line and one or more data lines for each
        logical CPU.

        HACK: we do not know the number of data lines, and there is no marker (such as a blank line)
        indicating the end of a single measurement. After reading a header line, read subsequent
        lines without blocking. A read timeout will indicate the end of a measurement.

        HACK: non-blocking reads are approximated by using a small timeout, as the queue
        is populated by a separate thread non-atomically.
        """
        n_skipped = 0
        while True:
            line = self.stdout_queue.get(**kwargs)
            items = line.text.split()
            if 'Core' in items and 'CPU' in items:
                header = line
                fields = items
                break
            n_skipped += 1

        if n_skipped > 0:
            self.service.warning(f"Skipped {n_skipped} lines before measurement header")

        parsed_data = []
        while True:
            try:
                line = self.stdout_queue.get(timeout=0.1)
            except (queue.Empty, queue.ShutDown):
                break

            # delay between successive lines means that we are reading the next measurement; stop
            if abs(line.timestamp_ns - header.timestamp_ns) > 0.1 * NSEC_PER_SEC:
                self.stdout_queue.unget(line)
                break

            items = line.text.split()

            # repeated header means that we are reading the next measurement; stop
            if 'Core' in items and 'CPU' in items:
                self.stdout_queue.unget(line)
                break

            if len(items) > len(fields):
                raise ErrorException(f"Invalid turbostat output: {line=!r}\n({header=!r})")

            # XXX: this assumes that there can be no gaps in turbostat data lines, i.e.,
            #      any fields that may be absent from a specific line (such as per-package data)
            #      always come after all fields that may not be absent.
            parsed_data.append(
                TurbostatLine(items=dict(itertools.zip_longest(fields, items, fillvalue=None)))
            )

        for line in parsed_data:
            if line.items.get('CPU') is None or line.items.get('Core') is None:
                raise ErrorException(f"Invalid turbostat output: {line!r}")
            if (line.items['CPU'] == '-') != (line.items['Core'] == '-'):
                raise ErrorException(f"Invalid turbostat output: {line!r}")
            if 'Package' in fields and line.items['Package'] is None:
                raise ErrorException(f"Invalid turbostat output: {line!r}")

        cpus_lines = [line for line in parsed_data if line.items['CPU'] != '-']
        cpus = {
            int(line.items['CPU']): line for line in cpus_lines
        }
        totals_lines = [line for line in parsed_data if line.items['CPU'] == '-']

        if len(cpus) != len(cpus_lines):
            raise ErrorException(
                f"Invalid turbostat output: duplicate CPU ids: {len(cpus)=}, {len(cpus_lines)=}"
            )
        if len(totals_lines) != 1:
            raise ErrorException(
                f"Invalid turbostat output: duplicate total lines: {len(totals_lines)=}"
            )

        measurement = TurbostatMeasurement(
            timestamp_ns=header.timestamp_ns,
            fields=fields,
            cpus=cpus,
            totals=totals_lines[0],
        )
        self._accumulate(measurement)
        return measurement



@dataclasses.dataclass(kw_only=True, frozen=True)
class CPUTopology:
    cpu: int
    thread_siblings: list[int]

    @staticmethod
    def _parse_sysfs_list(arg: str) -> Iterable[int]:
        for item in arg.split(','):
            start, sep, end = item.partition('-')
            if sep:
                yield from range(int(start), int(end) + 1)
            else:
                yield int(item)

    @classmethod
    @functools.cache
    def from_sysfs(cls, cpu: int, *, service: dblc.Service):
        sysfs_dir = Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')

        try:
            thread_siblings_raw = sysfs_dir.joinpath('thread_siblings_list').read_text()
            thread_siblings = list(cls._parse_sysfs_list(thread_siblings_raw))
        except (OSError, ValueError) as e:
            service.error(f"Cannot read thread siblings for CPU {cpu}: {e}")
            thread_siblings = [cpu]

        return CPUTopology(
            cpu=cpu,
            thread_siblings=thread_siblings,
        )


class DataType(enum.IntEnum):
    FREQUENCY = 1
    IPC = 2
    INTERRUPTS = 3
    RESIDENCE = 3
    POWER = 4
    TEMPERATURE = 5


CHART_PROTO = [
    ChartProto(
        type=DataType.FREQUENCY,
        representation=ChartType.GAUGE,
        name='avg_frequency',
        title='Average Frequency',
        unit_name='MHz',
        dimensions=(
            DimProto(source='Avg_MHz', per_device=True, id=None, label=None),
        )
    ),
    ChartProto(
        type=DataType.FREQUENCY,
        representation=ChartType.GAUGE,
        name='busy_frequency',
        title='Busy Frequency',
        unit_name='MHz',
        dimensions=(
            DimProto(source='Bzy_MHz', per_device=True, id=None, label=None),
        )
    ),
    ChartProto(
        type=DataType.IPC,
        representation=ChartType.GAUGE,
        name='ipc',
        title='Instructions Per Cycle',
        unit_name='instructions per cycle',
        ctor=float,
        store_ratio=Fraction(1000),
        dimensions=(
            DimProto(source='IPC', id='ipc', label='IPC'),
        )
    ),
    ChartProto(
        type=DataType.INTERRUPTS,
        representation=ChartType.COUNTER,
        name='irq',
        title='Hardware Interrupts (IRQs)',
        unit_name='interrupts',
        dimensions=(
            DimProto(source='IRQ', id='irq', label='IRQ'),
        )
    ),
    ChartProto(
        type=DataType.INTERRUPTS,
        representation=ChartType.COUNTER,
        name='nmi',
        title='Non-Maskable Interrupts (NMIs)',
        unit_name='interrupts',
        dimensions=(
            DimProto(source='NMI', id='nmi', label='NMI'),
        )
    ),
    ChartProto(
        type=DataType.INTERRUPTS,
        representation=ChartType.COUNTER,
        name='smi',
        title='System Management Interrupts (SMIs)',
        unit_name='interrupts',
        dimensions=(
            DimProto(source='SMI', id='smi', label='SMI'),
        )
    ),
]
CHART_PROTO_FROM_NAME = { x.name: x for x in CHART_PROTO }
CHART_PROTO_ORDER = { id(x): idx for idx, x in enumerate(CHART_PROTO) }


@dataclasses.dataclass(kw_only=True, frozen=True)
class Device(dblc.Device):
    class Kind(enum.IntEnum):
        Totals = 0
        CPU = 1
    kind: Kind
    package: Optional[int]
    core: Optional[int]
    sibling: Optional[int]
    cpu: Optional[int]

    @classmethod
    def make_totals(cls) -> Self:
        return cls(
            kind=cls.Kind.Totals,
            package=None,
            core=None,
            sibling=None,
            cpu=None,
        )

    @classmethod
    def make_cpu(cls, package: int, core: int, sibling: int, cpu: int) -> Self:
        return cls(
            kind=cls.Kind.CPU,
            package=package,
            core=core,
            sibling=sibling,
            cpu=cpu,
        )

    def make_dim_id(self) -> str:
        match self.kind:
            case Device.Kind.Totals:
                return 'total'
            case Device.Kind.CPU:
                return f'cpu{self.cpu}'

    def make_dim_label(self) -> str:
        match self.kind:
            case Device.Kind.Totals:
                return 'Total'
            case Device.Kind.CPU:
                return f'CPU {self.cpu}'

    def make_chart_family_suffix(self) -> Optional[str]:
        return None

    def make_chart_context_prefix(self) -> str:
        match self.kind:
            case Device.Kind.Totals:
                return 'total'
            case Device.Kind.CPU:
                return 'cpu'

    def make_chart_title_suffix(self) -> str:
        match self.kind:
            case Device.Kind.Totals:
                return '(total)'
            case Device.Kind.CPU:
                return '(per CPU)'

    def make_chart_id_prefix(self) -> str:
        match self.kind:
            case Device.Kind.Totals:
                return 'total'
            case Device.Kind.CPU:
                return f'cpu{self.cpu}'

    def make_chart_labels(self) -> dict[str, str]:
        chart_prefix = self.make_chart_id_prefix()
        match self.kind:
            case Device.Kind.Totals:
                return {
                    'item': chart_prefix,
                    'kind': 'total',
                }
            case Device.Kind.CPU:
                return {
                    'item': chart_prefix,
                    'kind': 'cpu',
                    'package': str(self.package),
                    'core': str(self.core),
                    'sibling': str(self.sibling),
                    'cpu': str(self.cpu),
                }


class Service(dblc.Service):
    BINARIES = [
        '/usr/bin/turbostat',
        '/usr/sbin/turbostat',
    ]
    SUDO = 'sudo'

    use_sudo: bool
    command: list[str]
    sudo: Optional[list[str]]
    turbostat: Optional[Turbostat]

    def __init__(self, configuration=None, name=None):
        super().__init__(
            configuration=configuration,
            name=name,
            plugin_id=PLUGIN_ID,
        )
        command = configuration.get('command')
        if command is None:
            command = next(b for b in self.BINARIES if os.path.exists(b))
        self.command = self._parse_cmd(command)

        self.use_sudo = configuration.get('use_sudo', True)
        self.sudo = Service._parse_cmd(
            configuration.get('sudo', Service.SUDO)
        ) if self.use_sudo else None
        self.turbostat: Optional[Turbostat] = None

    def make_chart_priority(self, chart: Chart) -> int:
        return self.priority + CHART_PROTO_ORDER[id(chart.proto)] * 2 + int(chart.device.kind)

    @staticmethod
    def _parse_cmd(cmd: str | list[str]) -> list[str]:
        if isinstance(cmd, str):
            return shlex.split(cmd)
        return cmd

    def _run_turbostat(self, args: list[str]):
        cmdline = list()
        if self.use_sudo:
            cmdline += self.sudo + [ '--' ]
        cmdline += self.command
        cmdline += args

        turbostat = Turbostat(cmdline, service=self)
        turbostat.run()
        return turbostat

    def _extract_device_data(self, *, builder: ChartBuilder, device: Device, line: TurbostatLine):
        for proto in CHART_PROTO:
            if proto.dimensions is None:
                continue
            for dim in proto.dimensions:
                value = line.items.get(dim.source)
                if value is None:
                    continue
                builder.submit(
                    proto=proto,
                    device=device,
                    item=dim,
                    value=proto.ctor(value),
                )

    def _get_data(self, *, turbostat: Turbostat, check: bool):
        chart_builder = ChartBuilder(self)

        # if by some chance we got multiple measurements buffered (we trigger a measurement manually
        # with a SIGUSR1, but we also have to provide an interval which cannot be infinite),
        # discard all but the last one
        ms = turbostat.measure(check=check)
        if len(ms) > 1:
            self.warning(f"Turbostat produced {len(ms)=} measurements, discarding all except last")
        measurement = ms[-1]

        device = Device.make_totals()
        self._extract_device_data(builder=chart_builder, device=device, line=measurement.totals)

        for idx, cpu in measurement.cpus.items():
            topology = CPUTopology.from_sysfs(cpu=idx, service=self)
            device = Device.make_cpu(
                package=int(cpu.items.get('Package', '0')),
                core=int(cpu.items['Core']),
                cpu=idx,
                sibling=topology.thread_siblings.index(idx),
            )
            self._extract_device_data(builder=chart_builder, device=device, line=cpu)

        chart_builder.build_charts()
        return chart_builder.build_data()

    def get_data(self):
        try:
            if self.turbostat is None:
                self.turbostat = self._run_turbostat([
                    '--quiet', '--interval', '1000'
                ])
            return self._get_data(check=False, turbostat=self.turbostat)
        except queue.ShutDown:
            # turbostat died
            self.error(f'Turbostat exited unexpectedly, restarting')
            self.turbostat.stop()
            self.turbostat.run()
            return None
        except NoDataException:
            return None
        except ErrorException as e:
            self.error(*e.args)
            return None
        except Exception as e:
            self.error(f'Failed to get data: {type(e)}: {e}')
            return None

    def check(self):
        try:
            with self._run_turbostat([
                '--interval', '1', '--num_iterations', '1'
            ]) as turbostat:
                return bool(self._get_data(turbostat=turbostat, check=True) and self.charts)
        except ErrorException as e:
            self.error(*e.args)
            return None
        except Exception as e:
            self.error(f'Failed to get data: {type(e)}: {e}')
            return None
        except:
            return None
