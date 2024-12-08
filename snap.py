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

from utils import *
from countpanic import *
import threading

def count_panic():
    print("start listening...")
    socketc = SocketClient("/tmp/qmp.sock")
    socketc.send('{"execute": "qmp_capabilities"}')
    socketc.listen()
    print("panic count: " + str(socketc.panic))

if __name__ == '__main__':
    # snapinject_ram(4800, 0.345 * 1e9, 0.345 * 1e9, 2 * 60, 10)
    counter = threading.Thread(target=count_panic)
    counter.start()
    snapinject_ram(3, 1 * 1e9, 2 * 1e9, 2, 2)
    counter.join()
