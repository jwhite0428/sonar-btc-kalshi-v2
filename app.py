from flask import Flask, jsonify, render_template, request
import requests, time
from datetime import datetime, timezone

app = Flask(__name__)
API = 'https://api.exchange.coinbase.com'
HEAD = {'User-Agent': 'SonarMobilePaper/1.0', 'Accept': 'application/json'}
_cache={}

def get_json(path, ttl=8):
    now=time.time()
    if path in _cache and now-_cache[path][0] < ttl: return _cache[path][1]
    r=requests.get(API+path,headers=HEAD,timeout=12)
    r.raise_for_status()
    data=r.json(); _cache[path]=(now,data)
    return data

@app.route('/')
def home(): return render_template('index.html')

@app.route('/api/candles')
def candles():
    tf=request.args.get('tf','1m')
    mapping={'15s':60,'1m':60,'3m':60,'5m':300,'15m':900,'1h':3600}
    if tf not in mapping: return jsonify({'error':'Invalid timeframe'}),400
    try:
        raw=get_json(f'/products/BTC-USD/candles?granularity={mapping[tf]}', 15)
        # Coinbase: [time, low, high, open, close, volume]
        bars=[{'t':int(x[0]),'o':float(x[3]),'h':float(x[2]),'l':float(x[1]),'c':float(x[4]),'v':float(x[5])} for x in raw]
        bars.sort(key=lambda x:x['t'])
        return jsonify({'bars':bars,'source':'Coinbase Exchange BTC-USD','historical_resolution_seconds':mapping[tf]})
    except Exception as e: return jsonify({'error':'Coinbase data unavailable: '+str(e)}),503

@app.route('/api/ticker')
def ticker():
    try:
        d=get_json('/products/BTC-USD/ticker',4)
        return jsonify({'price':float(d['price']),'time':d.get('time'),'volume':d.get('volume')})
    except Exception as e: return jsonify({'error':str(e)}),503

KALSHI_API = 'https://external-api.kalshi.com/trade-api/v2'

def _parse_timestamp(raw):
    if not raw: return None
    try: return datetime.fromisoformat(raw.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError): return None

def _quote(market, side):
    # Fixed-point dollar strings are the preferred official quote representation.
    val = market.get(side + '_dollars')
    if val not in (None, ''):
        try: return round(float(val) * 100, 2)
        except (TypeError, ValueError): return None
    # Legacy fields may be integer cents; never reinterpret dollar strings as cents.
    val = market.get(side)
    if isinstance(val, (int, float)): return round(float(val), 2)
    return None

def _strike(m):
    for k in ('floor_strike', 'cap_strike'):
        v=m.get(k)
        if v is not None:
            try: return float(v)
            except (TypeError, ValueError): pass
    return None

@app.route('/api/kalshi15')
def kalshi15():
    try:
        r=requests.get(KALSHI_API + '/markets', params={
            'series_ticker':'KXBTC15M', 'status':'open', 'limit':100,
        }, headers={'User-Agent':'SonarMobilePaper/2.0','Accept':'application/json'}, timeout=12)
        r.raise_for_status()
        data=r.json()
        now=time.time()
        markets=data.get('markets') or []
        eligible=[]
        for m in markets:
            opened=_parse_timestamp(m.get('open_time'))
            closes=_parse_timestamp(m.get('close_time'))
            if not closes or closes<=now or (opened is not None and opened>now): continue
            if str(m.get('status','')).lower() not in ('active','open'): continue
            eligible.append((closes,m))
        if not eligible:
            return jsonify({'available':False,'reason':'No currently tradable KXBTC15M contract returned by Kalshi.', 'checked_at':datetime.now(timezone.utc).isoformat()})
        closes,m=min(eligible, key=lambda x:x[0])
        return jsonify({
            'available':True,
            'ticker':m.get('ticker'), 'title':m.get('title'),
            'status':m.get('status'), 'close_time':m.get('close_time'),
            'open_time':m.get('open_time'), 'strike':_strike(m),
            'strike_type':m.get('strike_type'),
            'yes_bid_cents':_quote(m,'yes_bid'), 'yes_ask_cents':_quote(m,'yes_ask'),
            'no_bid_cents':_quote(m,'no_bid'), 'no_ask_cents':_quote(m,'no_ask'),
            'volume':m.get('volume_fp',m.get('volume')),
            'checked_at':datetime.now(timezone.utc).isoformat(),
            'source':'Kalshi public market feed',
            'settlement_warning':'Coinbase BTC/USD chart is not Kalshi settlement reference.'
        })
    except (requests.RequestException, ValueError, TypeError) as exc:
        return jsonify({'available':False, 'error':'Kalshi quote unavailable: ' + str(exc)}),503

@app.route('/health')
def health(): return jsonify({'ok':True})

if __name__=='__main__':
    import os
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT','5000')))
