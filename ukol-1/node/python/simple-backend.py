#!/usr/bin/python3 -u

import sys
import socket
import json
import random
import trio
import time
import math


MY_ID = random.randrange(10**9, 10**10) # for easier debugging, make all IDs 10-digit

def short_id(id): # show only prefix of ID for cleaner messages.. because all IDs have same length, this preserves ordering
    return str(id)[:4]

def debug(*a):  # tisk debug hlášek timestamp + zkrácené id + *a (libovolný počet parametrů) - message
    print(
         "[" + time.strftime("%H:%M:%S.%f")[:-3] + "][" + short_id(MY_ID) + "]",
         *a,
         file=sys.stderr)
    sys.stderr.flush()

PORT = 6666
BROADCAST = ('255.255.255.255', PORT)

ANNOUNCE_INTERVAL = 1 # [sekund]
NODE_TIMEOUT = 5
SLAVE_WAIT = 10
MASTER_WAIT = 15

peer_info  = {}    #slovník id + vnořené další info o stavu
cur_master = None
cur_master_candidate = None
master_candidate_since = None
my_color = None
assigned_colors = {}   # slovník s id všech a jejich barvy

def cleanup_stale():   # vyháže všechny, co se dlouho neozvali z peer_info
    now = time.time()
    for id, info in list(peer_info.items()):   # list vytvoří dočasnou kopii slovníku, jinak to nefacháiteruje přes items - klíč i hodnota 
        if now - info['last_seen'] > NODE_TIMEOUT:
            del peer_info[id]
            if id in assigned_colors: del assigned_colors[id]


def get_max_seen(): # nejvyšší id, které je aktivní 
    cleanup_stale()
    if not peer_info: return MY_ID  # pokud je slovník prázdný
    max_peer = max( peer_info.keys()  ) # vybere maximální id
    return max( MY_ID, max_peer ) 

def get_master_candidate():
    # projde všechny peer a porovná, zda i oni vidí stejné maximum, pak vráti shodu, nebo none
    max_seen = get_max_seen()
    for info in peer_info.values():
        if info['max_seen'] != max_seen: #neshodli jsme se
            return None
    return max_seen
    
def update_master(): # periodicky vyhodnocuje setrvání, či změnu mastera, testuje zda je kandidát aspoň 10s, po zapnutí master nikdo
    global cur_master, cur_master_candidate, master_candidate_since, my_color # pro zápis do globální proměnné nutno nadeklarovat, aby se nepobily lok a glob
    new_master_candidate = get_master_candidate()    
    if cur_master is not None:                  # Nějaký vybraný master již z dřívějška existuje
        if new_master_candidate == cur_master:
            return                              # je-li stávající master shodný s kandidátem return
        else:
            if cur_master == MY_ID:
                debug("I am no longer master")
            else:
                debug("Lost master")
            cur_master = None # pokud new není shodný s cur, tak to cur seberu
            if my_color:
                print("My color changed from", my_color, "to None")
                my_color = None # moje barva - zruším
    if cur_master_candidate == new_master_candidate:
        if cur_master_candidate == MY_ID: wait = MASTER_WAIT # jiné čekání, když sám sebe chci pasovat na mastera
        else: wait = SLAVE_WAIT
        # pokud je kandidát dostatečně dlouho 
        if cur_master_candidate is not None and time.time() - master_candidate_since > wait: # čekání na dobu ve wait
            cur_master = cur_master_candidate                   # pasuje kandidáta
            if cur_master == MY_ID:                             # pokud jsem to já, nastavím si zelenou    
                debug("I have become master. I am now green.")
                assigned_colors = {}
                my_color = 'g'
            else:
                debug("Got new master:", short_id(cur_master))
                my_color = None # pokud se změní master, reset mou barvu 
    else:
        cur_master_candidate = new_master_candidate     #pokud nebyla shoda, nový kandidát na čekací pozici curr
        master_candidate_since = time.time()
        debug("Got new master candidate:", short_id(cur_master_candidate))


def handle_announce(packet):      # zpracování a uložení přijatého paketu broadcastu od jiného peera
    global my_color
    peer_id = packet['id']
    if peer_id == MY_ID: return # přišel mi zpátky muj packet (občas se to stane)
    packet['last_seen'] = time.time()       # přidám timestamp a uložím si do své "databáze" peerů
    peer_info[peer_id] = packet
    update_master()                         # kontrola mastera
    if cur_master == peer_id and 'assigned_colors' in packet:  # assigned_colors slovník id-barva
        new_color = packet['assigned_colors'].get(str(MY_ID), None) # získám svou barvu Json string pro klíč, vrátí mou barvu, nebo none
        if new_color != my_color:
            debug("My color changed from", my_color, "to", new_color)
            my_color = new_color


async def listen_for_announces():  # asynchronní aby bylo možno pustit dvě corutiny tuhle a send_announces() jako kdyby dvě vlákna
    while True:
        data = await announce_sock.recv(8192)     # await - zde to může chvíli čekat a může běžet další rutina, než přijde packet
        try: info = json.loads(data.decode('utf-8'))    #  data.decode('utf-8') převede bajty na string, json.loads udělá slovník z jsona
        except ValueError: continue # invalid encoding
        #debug("Got announce", info)  # tisk pro debug
        handle_announce(info)

def assign_colors():  # volá se pravidelně kontroluje zda má každý barvu a případně řeší poměry barev
    cleanup_stale()
    for id in list(assigned_colors.keys()):
        if id != MY_ID and id not in peer_info:  # pokud je přiřazená barva někomu kdo zmizel, smažu 
            del assigned_colors[id]
    num_nodes = len(peer_info) + 1  # celkem živých modů, o kterých vím + já
    want_color = {}                 # slovník s počty požadované pro jednotlivé barvy
    want_color['g'] = int(math.ceil(num_nodes / 3)) # dle zadání 1/3 zaokrouhlená nahoru
    want_color['r'] = num_nodes - want_color['g']
    want_color['g'] -= 1 # odečtu sebe, když jsem master - mám být stále zelený 
    cur_color = {'g': 0, 'r': 0}
    unassigned_peers = []
    for id in peer_info.keys():
        color = assigned_colors.get(id, None)
        if color:
            if cur_color[color] >= want_color[color]: # pokud je počet barev >= požadavku
                color = None                            
                assigned_colors[id] = None              # smažu barvu
                unassigned_peers.append(id)             # seznam těch, co nemají barvu
            else:
                cur_color[color] += 1                   # inkrementuji počet dané barvy    
        else:
            unassigned_peers.append(id)                 # pokud neměl barvu přidám do listu čekatelů
    for peer_id in unassigned_peers:
        for color in ('g', 'r'):                            
            if cur_color[color] < want_color[color]:    # pokud je menší než požadovaný počet,  
                assigned_colors[peer_id] = color        # přidělím
                cur_color[color] += 1                   # inkrementuju počet přidělených    
                break

    assigned_colors[MY_ID] = 'g'                        # jsem master, dám si zelenou
    return assigned_colors

        

last_printed_colors = None
async def send_announce():              # odeslání paketu periodicky, 
    global last_printed_colors          # ohlášen zápis do globální proměnné z funkce musí mít global
    info = {'id': MY_ID, 'max_seen': get_max_seen(), 'color': my_color}  # pokud nejsem master, dám do slovníku jen tohle
    if cur_master == MY_ID:             # pokud jsem master, přidám přiřazení barev
        info['assigned_colors'] = assign_colors()  # master-do klíče 'assigned_colors' uloží celý slovník co vypadne z fce assign_colors
        if info['assigned_colors'] != last_printed_colors:  # vypisuji jen při změně
            last_printed_colors = dict(info['assigned_colors']) # vatvoří kopii slovníku pro příští porovnání
            debug("Assigned colors:", info['assigned_colors'])
    data = json.dumps(info).encode('utf-8')                 # přechroupe slovník na json
    await announce_sock.sendto(data, BROADCAST)             # v případě, že blokuje, může se dělat něco jiného

async def send_announces():
    while True:
        await send_announce()               # odeslání paketu
        await trio.sleep(ANNOUNCE_INTERVAL) # čeká 1 sec

async def main():
    global announce_sock
    announce_sock = trio.socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # vytvoří se socket z tria inet - ip síť , dgram - UDP
    announce_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)    # nastaví parametry
    await announce_sock.bind(('', PORT))                                   # na kterém portu má poslouchat 
    async with trio.open_nursery() as nursery:                             # 
        nursery.start_soon(listen_for_announces)
        nursery.start_soon(send_announces)

debug("Starting")
trio.run(main)


