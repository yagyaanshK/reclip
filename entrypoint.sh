#!/bin/bash
# Ensure DNS resolution works at runtime (resolv.conf may be overwritten by container runtime)
if [ -w /etc/resolv.conf ]; then
    printf "nameserver 8.8.8.8\nnameserver 1.1.1.1\n" > /etc/resolv.conf
fi
exec python app.py
