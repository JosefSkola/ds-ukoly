#!/usr/bin/python3

import sys,os                     # práce se soubory, argv, env apod
import json
import time
from flask import Flask, request  # https příchozí požadavek, když jsem server 
from kazoo.client import KazooClient
import logging                    # modul pro logování , používá interně flask a asi i kazzoo
import requests                   # knihovna umožňující odesílat požadavky - když jsem klient
from threading import Thread

logging.basicConfig()             # inicializace logingu pro flask

zk_ip = os.environ['ZOO_SERVERS'] # získá obsah systémových proměnných , z vagrantu
my_id = int(os.environ['MY_ID'])
my_ip = os.environ['MY_IP']
root_id = int(os.environ['ROOT_ID'])
is_root = (my_id == root_id)        # jsem root ?? -> 1    


zk = KazooClient(hosts=zk_ip)       # zk zookeper klient
zk.start()

def log(*a):                        # tisk libovolný počet argumentů libovolného typu
    print("["+str(my_id)+"]", *a, file=sys.stderr)
    sys.stderr.flush()

if is_root:                         # pokud jsem root 
    # Tree position encoding:       # strom klientů ZK
    #            1
    #      2           3
    #   4     5     6     7
    #  8 9  10 11 12 13 14 15
    # ....
    # Parent of node (i) is (i//2)  # index parenta uzlu
    tree = {1: (my_id, my_ip)}      # root má index 1
    my_zk_path = '/' + str(my_id)   # root má tedy /1  path
    parent_url = None               # root nemá parents
    parent_zk_path = None
    log("I am root")
else:                               # nejsem root                         
    root_ip = os.environ['ROOT_IP'] # 
    root_url = 'http://' + root_ip + ':5000'
    log("Connecting to root", root_url)
    while True:
        try:        #v- požádám roota  '/clients/register' (Flask) aby mě zaregistroval. Odpověď přechroupu do JSON
            info = requests.post(root_url + '/clients/register', params={'id': my_id, 'ip': my_ip}).json()
        except requests.ConnectionError:    # chyba spojení
            log("Could not connect to root, retrying")
            time.sleep(1)
            continue
        else:
            break                           # request OK
    log("Connected, got", info)
    my_zk_path = info['zk_path']            # z JSON odpovědi path na zookeeperu
    parent_ip = info['parent_ip']
    parent_id = info['parent_id']
    parent_url = 'http://' + parent_ip + ':5000'


zk.ensure_path(my_zk_path)                  # zajistit aby cesta existovala je vnitřní fuknkcionalita zk
zk_data = {'ip': my_ip, 'id': my_id}        # Něco tam uložím
zk.set(my_zk_path, json.dumps(zk_data).encode('utf-8'))  # byte řetězec do JSON 

app = Flask(__name__)                       # spustí flask

store = {}                                  # slovník, KVS kam si ukládám to o čem vím

    

@app.get('/kv/<key>')                       # vrátí hodnotu na požadovaném klíči
def get(key):
    log("GET", key)
    if key in store:
        log("Found here", key)
        return store[key]
    elif is_root:
        log("Not found in root", key)
        return 'key not found', 404
    else:                                   # klíč nemám, jdu za rodičem
        log("Forwarding to parent", parent_id, parent_url)
        r = requests.get(parent_url + '/kv/' + key) # pošlu stejný request rodiči na jiné mašině
        log("Got value from parent", repr(r.content)) # repr vytvoří něco tisknutelného do logu
        if r.status_code == 200:            # is OK ?  
            store[key] = r.content          # uložím u sebe
        return r.content, r.status_code     # vracím jako HTTP odpověď  dvojice text

@app.put('/kv/<key>')                       # ukládám hodnotu na klíč
def put(key):
    value = request.get_data()              # payload data pro KVS 
    wait_propagate = int(request.args.get('wait_propagate', '1'))  # get metoda na argumentech slovníku https default '1' (zatím prázdno) '1' abych čekal 
    log("PUT", key, repr(value), wait_propagate)
    store[key] = value                      # uloží hodnotu z put
    if not is_root:
        def propagate_to_parent():          # přepošle to parent 
            propagate_url = parent_url + '/kv/' + key + '?wait_propagate=0' # wait_propagate=0 už na nic nečekáme, takže se to pustí v dalším vlákně
            requests.put(propagate_url, data=value)                         # pošlu
        if wait_propagate:                  # pokud mám čekat na odpověď 
            log("Propagating with wait")
            propagate_to_parent()           # přepošlu na parent blokující
        else:
            log("Propagating without wait") # pustím v dalším vlákně 
            Thread(target=propagate_to_parent).start()
    return '', 200

# skoro stejné jako  put() pro přehlednost ponecháno tak
@app.delete('/kv/<key>')
def delete(key):
    wait_propagate = int(request.args.get('wait_propagate', '1'))
    try: del store[key]
    except KeyError: pass       # pokud chci smazat něco co tam nebylo (Keyerror) udělám pass - nic
    if not is_root:
        def propagate_to_parent():
            propagate_url = parent_url + '/kv/' + key + '?wait_propagate=0'
            requests.delete(propagate_url)
        if wait_propagate:
            propagate_to_parent()
        else:
            Thread(target=propagate_to_parent).start()
    return '', 200

if is_root:
    def build_zk_path(tree_pos):   # sestaví cestu pro ZK 
        if tree_pos == 0: return ''
        else:
            node_id, node_ip = tree[tree_pos]  # použiju jen id 
            return build_zk_path(tree_pos // 2) + '/' + str(node_id) # rekurze poskládá cestu + poslední
    @app.post('/clients/register') # registrace klienta 
    def register_client():          
        client_id = int(request.args['id']) # posílám při žádosti
        client_ip = request.args['ip']
        log("Got register request", client_id, client_ip)
        tree_pos = len(tree) + 1            # nový klient dostane staré +1
        parent_pos = tree_pos // 2          # spočtu parent
        parent_id, parent_ip = tree[parent_pos] 
        tree[tree_pos] = (client_id, client_ip) # uložím nového klienta
        zk_path = build_zk_path(tree_pos)       # poskládám cestu 
        reply = {'parent_id': parent_id, 'parent_ip': parent_ip, 'zk_path': zk_path}  # odpověď klientovi 
        log("Replying", reply)
        return reply





app.run(host='0.0.0.0', port=5000)
