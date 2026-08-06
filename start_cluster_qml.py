"""QML-build twin of start_cluster.py: reader threads + the Qt Quick cluster."""
import os
from concurrent.futures import ThreadPoolExecutor

from bt_media_helper import read_bt_media
from can_helper import read_can, log_realtime
from gpio_helper import read_io
from gps_helper import read_gps
from cluster_qml import run_cluster
from model import SensorState

if __name__ == '__main__':
    state = SensorState()

    # every submitted reader blocks forever, so max_workers must cover them all
    ex = ThreadPoolExecutor(max_workers=6, thread_name_prefix="ftcan")
    can_reader = ex.submit(read_can, state=state)
    io_reader = ex.submit(read_io, state=state)
    gps_reader = ex.submit(read_gps, state=state)
    bt_reader = ex.submit(read_bt_media, state=state)

    if os.environ.get('CAN_DEBUG', 'true').lower() == 'true':
        ex.submit(log_realtime)

    run_cluster(state)

    # The reader threads block forever in their read loops and are non-daemon
    # (executor threads), so a normal exit would hang joining them. Nothing
    # here needs graceful teardown — state is in-memory only.
    os._exit(0)
