Popis funkcionality úlohy 1 z předmětu distribuované systémy

# Princip fungování

## Komunikace

Nody komunikují pomocí broadcast UDP paketů odesílaných na port 6666. Předpokládáme, že jsou všechny na stejné L2 síti. Pakety jsou formátované jako JSON. Každý node má
své ID (náhodně vygenerované při startu), které je součástí odesílaných paketů.

## Seznamy sousedů

Každý uzel odesílá oznamovací pakety v pravidelných intervalech (každou vteřinu).

Každý node si drží seznam "sousedů" (peers) - ostatních aktivních uzlů v síti, o kterých ví. Soused je považován za aktivního, pokud od něj byl obdržen paket v posledních 5s. Jinak je považován za mrtvého, je ze seznamu sousedů vyřazen a dál
se protokolu neúčastní.

## Volba mastera

Princip je jednoduchý: chceme, aby se masterem stal uzel s nejvyšším ID.

Abychom pokud možno zamezili štěpení sítě a situacím, kdy dočasně existuje více masterů, obsahuje algoritmus ještě několik dodatečných ochranných opatření.

Uzly ve svých oznamovacích paketech posílají kromě vlastního ID ještě nejvyšší aktivní ID, o kterém ví (maximum ze svého ID a ID svých aktivních sousedů).

Uzel **A** považuje uzel **B** (sebe nebo některého ze svých sousedů) za *kandidáta na mastera*, pokud jsou splněny dvě podmínky:
1. ID **B** je nejvyšší z aktivních ID, o kterých **A** ví
2. Všichni sousedé **A** se shodnou na tom, že **B** vidí jako nejvyšší ID

Pokud se **A** se svými sousedy neshodne na nejvyšším ID, **A** nikoho nepovažuje za
kandidáta na mastera (a tedy ani za mastera). Tato situace by vždy měla být pouze dočasná, kromě podivných případů jako selektivní selhání doručování paketů mezi specifickou dvojicí uzlů.

Uzel je povýšen na mastera poté, co zůstane v roli kandidáta dostatečně dlouhou dobu
beze změny. (Přesněji ostatní uzly přijmou kandidáta za svého mastera po 10s, master
začně vykonávat svoji roli po 15s.) To by mělo zajistit větší stabilitu algoritmu, zvlášt v rané fázi, kdy startují postupně jednotlivé nody a nejvyšší ID se opakovaně
mění.

Pokud se po volbě mastera objeví uzel s vyšším ID, původní master o svou roli přichází
a volba začíná znovu.

## Barvení

Master jednostranně přiděluje barvy všem uzlům. Kompletní přiřazení barev posílá
broadcastem v rámci svého oznamovacího paketu, na základě něj ostatní uzly nastaví
svou barvu.


# Popis implementace

Celý úkol je napsán v jazyce Python. 

Pro funkcionalitu spojenou s asynchronním během rutin, je použita knihovna Trio. (https://www.root.cz/clanky/soubezne-a-paralelne-bezici-ulohy-naprogramovane-v-pythonu-knihovna-trio/)
To umožňuje současně vysílat i přijímat síťové packety mezi jednotlivými node a tak dosáhnout požadovaných vlastností. 

zdrojový kód jednotlivých node je uložen v adresáři python v souboru simple-backend.py

Na začátku je vygenerováno náhodné id číslo - MY_ID.

Funkce short_id(id) zkrátí id na 4 digit, aby debug hlášky byly přehlednější (není nutno používat).

Funkce debug(*a) slouží pro tisk debug hlášek - timestamp + zkrácené id + *a libovolný počet parametrů, které print vytiskne za sebou.

Dále jsou nastaveny některé konstanty a inicializovány některé proměnné.
Funkce cleanup_stale() pročistí na základě vypršeného timeoutu nody z peer_info

get_max_seen() vybere maximální hodnotu ze známých nodů, pokud je slovník peer_info prázdný, použije své id, jiné nemá.

Funkce get_master_candidate() projde všechny nody v peer_info a porovná, zda i oni vidí stejné maximum, pak vráti hodnotu, na které se shodli-> kandidáta na mastera , nebo none, pokud se neshodli.

Funkce update_master()  periodicky vyhodnocuje setrvání, či změnu mastera, testuje zda je kandidátem alespoň 10s. Po zapnutí není master nikdo.
Zkontroluje, je-li stávající master shodný s kandidátem, pokud ano, neděje se nic - return. Pokud ne pak stávajícího mastera vynuluji, svou barvu vynuluju a vypíši do logu. 
Pokud je cur_master_candidate == new_master_candidate, pak pokud jsem to já, nastavím delší čekání - MASTER_WAIT, pokud někdo jiný, kratší SLAVE_WAIT. Pokud čas čekání vypršel - pasuji kandidáta na mastera. Pokud jsem to já, nastavím si rovnou zelenou barvu, vypíši se do logu. Pokud nejsem master já, vypíši do logu "Got new master:" a vynuluji si barvu. 
Pokud se cur_master_candidate != new_master_candidate pak  cur_master_candidate je nahrazen new_master_candidate a vše pokračuje cyklicky dále. Do logu se vypíše "Got new master candidate:". 




handle_announce(packet) zpracování a uložení přijatého paketu - broadcastu od jiného peera - nodu

listen_for_announces():  naslouchání - asynchronní spolu s send_announces() aby bylo možno pustit tyto dvě corutiny  podobně jako dvě vlákna. Zachytí packet a převede jej na string, což je Json a ten pak na slovník.

assign_colors():  Volá se pravidelně, kontroluje, zda má každý barvu a případně řeší poměry barev.
Do slovníku assigned_colors se ukládají id a barvy, krom této funkce je použit při odesílání broadcastu se seznamem nódů a jejich barev od mastera. Tato funkce zajišťuje rozdělení varev v požadovaném poměru 1/3 : 2/3.

async def send_announce() pošle jednu zprávu, broadcast. Pokud nejsem master, pošle jen svoje id a barvu a max_seen tedy nejvyšší "viděné" id. Pokud jsem master tak se do packetu přidá ještě celý slovník assigned_colors 

async def send_announces() periodicky odesílá po 1 sekundě, mezitím stav await.

async def main()  spustí paralelně korutiny send_announces a listen_for_announces