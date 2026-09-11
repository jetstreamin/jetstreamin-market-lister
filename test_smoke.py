#!/usr/bin/env python3
import json, os, pathlib, tempfile
with tempfile.TemporaryDirectory() as t:
    os.environ['JETSTREAMIN_DATA']=t
    import app
    with app.db() as c:
        c.execute("INSERT INTO items(id,created_at,updated_at,title,description,condition_text,category,price,quantity,shipping) VALUES(?,?,?,?,?,?,?,?,?,?)",('demo',app.now(),app.now(),'1938 Congressional Cover','Historic mailed cover.','Visible handling wear.','Stamps > Covers',3,1,'Calculated shipping'))
        c.execute("INSERT INTO auctions(id,item_id,start_price,increment,ends_at) VALUES(?,?,?,?,?)",('sale','demo',3,1,'2026-09-15T20:00'))
        c.execute("INSERT INTO bids(auction_id,bidder,amount,created_at) VALUES(?,?,?,?)",('sale','collector1',4,app.now()))
        c.execute("INSERT INTO bids(auction_id,bidder,amount,created_at) VALUES(?,?,?,?)",('sale','collector2',6,app.now()))
    item=app.item_full('demo')
    assert item['auction']['bids'][0]['bidder']=='collector2'
    for channel in ('ebay','whatnot','facebook'):
        payload=app.channel_payload(item,channel)
        assert payload['format'].startswith(channel.upper())
    print('PASS: SQLite catalog, auction winner, and 3 channel exports')
