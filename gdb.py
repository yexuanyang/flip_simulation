# ==============================================================================
# This file tests the frequency of failures in a machine after experiencing 
# multiple single event upsets over a long period of operation.
# 
# Note: This file should run in Host machine.
# 
# Author: Yexuan Yang <myemailyyxg@gmail.com>
# Date: 2024-10-18
# ==============================================================================

from utils import *
import time

if __name__ == '__main__':
    """
    Except there will be 10 bits flip occur in 1 GB RAM per month.
    For 5 years and 16 GB RAM machine in space, there will be 5 * 12 * 16 * 10 = 9600 times flip.
    There are 5 * 360 * 24 * 3600 = 155,520,000 seconds in 5 years, so one flip occurs every 155520000 / 9600 = 16200 seconds.
    One bit flip use nearly 0.155s in program, we assume 0.5s in program as 16200s in real world, 
    so program sleep 0.345s after every flip.
    We simulate 8G machine in 5 years, in other word we simulate 4800 times flip. 
    Because every flip takes 0.5s in program so the program will run 40 minutes.
    """
    # autoinject_ram(4800, 0.345 * 1e9, 0.345 * 1e9)

    # Simple test suite to get the flip latency
    st = time.time()
    autoinject_ram(100, 20, 50)
    et = time.time()
    print("100 duration %.3fs" % (et - st))

    st = time.time()
    autoinject_ram(10, 20, 100)
    et = time.time()
    print("10 duration %.3fs" % (et - st))
    