#!/bin/bash
rust-gdb -q \
-ex 'set logging enable on' \
-ex 'target remote:1234' \
-ex 'maintenance packet Qqemu.PhyMemMode:1' \
-x gdb_command.txt \
-ex 'detach' -ex 'quit'
