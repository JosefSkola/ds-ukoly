# Key-value store

Práce je vytvořena v Pythonu.
Veškerá funkcionalita key-value store je soustředěna v modulu kvstore.py
    
Jsou importovány knihovny:
  * sys, os  pro práci s argumenty a proměnnými prostředí
  * time pro funkci sleep()
  * flask pro vlastní obsluhu požadavků serverem
      - objekt request poskytující informace o aktuálně zpracovávaném požadavku
  * requests pro vytváření odchozích HTTP požadavků
  * kazoo.client pro vytvoření instance klienta pro zookeeper
  * logging pro logování z flask a kazoo
  * threading pro spuštění v dalším vlákně
Po spuštění jsou získány informace ze systémových proměnných, kam byly uloženy Vagrantem.
Je to IP adresa Zookeeperu, vlastní IP adresa, vlastní ID, ID kořenového uzlu a IP adresu kořenového uzlu.

Je nastartován kazoo.client s IP adresou Zookeeperu.

Pokud jesm root, uložím patřičné informace (root ID a IP) do slovníku tree.
Pokud nejsem root použiji informace o root z enviromentu a požádám root o registraci.
To, co je mi od root vráceno, uložím do globálních proměnných (`my_zk_path`, `parent_id`, `parent_url`).

## Definice Flask rout

### Routy pro manipulaci s key-value store (cesta `/kv/<klíč>`)

Všechny operace nad key-value store používají URL cestu `/kv/<klíč>`. V rámci ní jsou implementované tři
HTTP metody dle zadání (GET, PUT, DELETE).

#### Metoda GET

Volání get najde hodnotu na zadaném klíči. Pokud jí nemá, zeptá se „nahoru ve stromu“ parenta, ten opět parenta a končí to dotazem
na root. Zpětné dotazy „dolů“ do jiných větví nebyly implementovány (viz zadání). Pokud hodnotu klíče nenajdu, vrátí kořen hodnotu
404, která probublá zpět jako výsledek.

#### Metody PUT a DELETE

Volání put slouží k uložení hodnoty na zadaný klíč. Ta je uložena primárně do stromu v nodu (klientu) který dotaz obdržel a pak je
propagována stromem „nahoru“ až do rootu.
Dle zadání se má  čekat na odpověď jen při prvním volání parenta. K tomu je využit atribut wait_propagate a poprvé je dotaz na
parenta spuštěn ve stejném vláknu tedy se čeká. V dalším případném volání je pak spuštěn v novém vláknu.

V podstatě stejným způsobem je obsloužena i routa delete.

V obou případech je uložená hodnota propagována jen nahoru a poslední, kdo ji obdrží a uloží je root. Zpětně do dalších větví stromu
„dolů“ již propagována není.

### Routa pro registraci klientů (cesta `/clients/register`, metoda `POST`)

Poslední routa zajišťuje registraci nového klienta na serveru. Na základě požadavku klienta, server vráti nové  klientské id,
zk_path a ID a IP rodiče.

## Zajištění koherence

Koherenci lze zajistit dvěma jednoduchými způsoby, v závislosti na scénáři použití:

### Scénář 1: zápisy jsou málo časté

V případě, že zápisy jsou málo časté, můžeme si dovolit po každém zápisu aktualizovat
hodnoty ve všech vrcholech, které mají daný klíč nakešovaný. To lze udělat např. tak,
že poté, co zápis doputuje do kořene, kořen inicializuje zpětný zápis směrem dolů --
pošle novou hodnotu svým dvěma potomkům. Pokud daný potomek nemá hodnotu nakešovanou,
může předpokládat, že ji nemá ani nikdo pod ním a může proces ukončit. Jinak opět pošle
aktualizaci svým dvěma potomkům. Tím, že všechny zápisy směrem dolů iniciuje kořen, je
zajištěna jejich serializace, a tedy i eventuální konvergence (v klidovém stavu, když
se chvíli do daného klíče nezapisuje, uvidí všechny uzly stejnou hodnotu).

### Scénář 2: zápisy jsou časté, ale nepotřebujeme vždy číst aktuální data

Pokud jsou zápisy časté (např. stejně časté jako čtení), určitě nemá smysl po každém
aktualizovat hodnoty ve všech vrcholech cache, to by bylo pomalejší než řešení bez
cache. Pokud bychom např. měli strom hloubky 5 a byli bychom se ochotní smířit s tím,
že při čtení dostaneme nejvýše 5 minut starou hodnotu, můžeme to vyřešit tak, že každý
vrchol si bude u záznamu v key-value store pamatovat i timestamp kdy jej obdržel. Pokud
je záznam starší než 1 minuta, je považován za neplatný a požadavek na čtení se předá
nadřazenému vrcholu (jen v kořenovém vrcholu mají záznamy neomezenou platnost, ten
považujeme za "zdroj pravdy").

Tak je zajištěno, že čtu hodnotu, kterou jsem obdržel nejvýše před minutou, kterou můj
rodič obdržel nejvýše před minutou, atd. až do kořene... tedy celkem nemůže být hodnota
starší než <počet pater stromu> minut.
