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
import uuid

tmpname = uuid.uuid4()

if __name__ == '__main__':
    address_dict = extract('iomem.txt')
    vm_action('savevm', tmpname)
    print(f"savevm {tmpname}")
    # for i in range(10):
        # flip_bit_in_area(address_dict, 'System RAM')
        # time.sleep(10 * 60)
        # vm_action('loadvm', tmpname)
    time.sleep(10)
    vm_action('delvm', tmpname)
    print(f"delvm {tmpname}")
