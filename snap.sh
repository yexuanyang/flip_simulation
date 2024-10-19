#!/bin/bash
if [ "$1" == "load" ]; then
    echo "loadvm tmpsnap" | socat - /tmp/qemu_socket
elif [ "$1" == "save" ]; then
    echo "savevm tmpsnap" | socat - /tmp/qemu_socket
elif [ "$1" == "del" ]; then
    echo "delvm tmpsnap" | socat - /tmp/qemu_socket
else
    echo "Invalid argument. Use 'load', 'save' or 'del'."
    exit 1
fi