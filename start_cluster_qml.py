"""QML-build twin of start_cluster.py: reader threads + the Qt Quick cluster."""
import os
from concurrent.futures import ThreadPoolExecutor

from can_helper import read_can, log_realtime
from gpio_helper import read_io
from gps_helper import read_gps
from cluster_qml import run_cluster
from model import SensorState

if __name__ == '__main__':
    state = SensorState()

    ex = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ftcan")
    can_reader = ex.submit(read_can, state=state)
    io_reader = ex.submit(read_io, state=state)
    gps_reader = ex.submit(read_gps, state=state)

    if os.environ.get('CAN_DEBUG', 'true').lower() == 'true':
        ex.submit(log_realtime)

    run_cluster(state)
