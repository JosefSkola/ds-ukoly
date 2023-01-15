#!/usr/bin/python3

import sys,os
import requests

def usage():
    print("usage: cli.py <server-ip> <get|put|delete> <key> [value]")
    sys.exit(1)

if len(sys.argv) < 4:
    usage()

server_ip = sys.argv[1]
action = sys.argv[2]
key = sys.argv[3]
url = 'http://' + server_ip + ':5000/kv/' + key

if action == 'get':
    sys.stdout.buffer.write(requests.get(url).content + b'\n')
elif action == 'put':
    if len(sys.argv) != 5: usage()
    requests.put(url, data=sys.argv[4])
elif action == 'delete':
    requests.delete(url)
else:
    usage()
