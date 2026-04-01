#!/bin/bash
# Fix DNS resolution for HF Spaces (runs as root, then drops to appuser)
printf "nameserver 8.8.8.8\nnameserver 1.1.1.1\n" > /etc/resolv.conf 2>/dev/null
exec gosu appuser python app.py
