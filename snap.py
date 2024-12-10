# ==============================================================================
# This file tests the failure rate of a machine after a single particle 
# flip occurs and the machine runs for a period of time. 
# The testing method is to save a snapshot of the machine before the flip, 
# run it for a period of time after the flip, record the running status, 
# then load the previous snapshot and repeat the experiment.
# 
# Author: Yexuan Yang <myemailyyxg@gmail.com>
# Date: 2024-10-18
# ==============================================================================

from fliputils import *
from countpanic import *
import threading

if __name__ == '__main__':
    # snapinject_ram(4800, 0.345 * 1e9, 0.345 * 1e9, 2 * 60, 10)
    counter = threading.Thread(target=count_panic, args=("/tmp/qmp.sock",))
    counter.start()
    snapinject_ram(1, 1 * 1e9, 2 * 1e9, 10, 6)
    counter.join()
