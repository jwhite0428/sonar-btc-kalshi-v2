"""SONAR V3 · BTC / Kalshi 15m · Streamlit Community Cloud.
Read-only public feeds; all trade activity is simulated in session state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import math
import time

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

COINBASE = 'https://api.exchange.coinbase.com/products/BTC-USD'
KALSHI = 'https://external-api.kalshi.com/trade-api/v2'
HEADERS = {'User-Agent': 'Sonar-BTC-Kalshi-Streamlit-Paper/3.0', 'Accept': 'application/json'}
TF = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600}

st.set_page_config(page_title='SONAR | BTC + Kalshi', page_icon='📊', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
:root{color-scheme:dark}
.stApp,[data-testid="stAppViewContainer"]{background:#080e11!important;color:#eff7f3!important}
.block-container{max-width:1000px;padding:1rem 1rem 4rem!important}
header[data-testid="stHeader"]{background:#080e11!important}
h1,h2,h3,p,small,label,[data-testid="stMarkdownContainer"]{color:#eff7f3}
h1{font-size:clamp(1.75rem,7vw,2.7rem)!important;letter-spacing:-.055em;margin-bottom:0!important}
h2,h3{letter-spacing:-.025em}
[data-testid="stCaptionContainer"],.stCaption{color:#a4b9b7!important}
[data-testid="stMetric"]{background:#101c20;border:1px solid #304448;border-radius:12px;padding:.75rem}
[data-testid="stMetricLabel"] *,[data-testid="stMetricLabel"]{color:#b5c9c7!important}
[data-testid="stMetricValue"] *,[data-testid="stMetricValue"]{color:#fff!important}
[data-testid="stSidebar"]{background:#101a1d}
[data-testid="stExpander"]{border:1px solid #304448;border-radius:12px}
[data-testid="stTabs"] button{color:#d7eeea!important}
.stButton>button[kind="primary"]{background:#b6f64b!important;color:#101911!important;border:0;font-weight:700}
.stButton>button{border-radius:10px!important}
.sonar-sub{color:#99b6b1;margin:.3rem 0 1rem;font-size:.85rem}
.sonar-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin:.55rem 0 1rem}
.sonar-tile{background:#122024;border:1px solid #345054;border-radius:12px;padding:12px;min-width:0}
.sonar-k{font-size:.72rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#b4c9c6}
.sonar-v{font-size:clamp(1.05rem,4.1vw,1.65rem);font-weight:760;color:#f8fffc;margin-top:4px;overflow-wrap:anywhere}
.sonar-v.good{color:#c5fa69}.sonar-v.bad{color:#ff8997}.sonar-v.warn{color:#ffd37d}
.sonar-status{border:1px solid #49604b;background:#17241d;padding:14px;border-radius:12px;margin:12px 0}
.sonar-status.nogo{border-color:#514447;background:#21191c}
.sonar-status strong{color:#eff7f3;font-size:1.2rem}.sonar-status p{color:#c7d8d4;font-size:.86rem;margin:.35rem 0 0}
.sonar-chip{display:inline-block;margin:3px 5px 3px 0;padding:4px 8px;border-radius:7px;background:#1d3132;color:#d9efea;font-size:.75rem}
.sonar-note{color:#acc2bd;font-size:.79rem;line-height:1.5}
@media(min-width:700px){.sonar-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.block-container{padding-top:1.5rem!important}}
@media(max-width:600px){.block-container{padding-left:.65rem!important;padding-right:.65rem!important}.stPlotlyChart{margin-left:-.35rem;margin-right:-.35rem}div[data-testid="stVerticalBlock"]{gap:.55rem}}
</style>''', unsafe_allow_html=True)


def get_json(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=12)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=13, show_spinner=False)
def candles(seconds):
    raw = get_json(f'{COINBASE}/candles', {'granularity': seconds})
    if not isinstance(raw, list) or len(raw) < 35:
        raise ValueError('Insufficient Coinbase candles')
    df = pd.DataFrame(raw, columns=['ts', 'low', 'high', 'open', 'close', 'volume'])
    for key in ('ts', 'low', 'high', 'open', 'close', 'volume'):
        df[key] = pd.to_numeric(df[key], errors='coerce')
    df = df.dropna().drop_duplicates('ts').sort_values('ts').tail(240).reset_index(drop=True)
    df['date'] = pd.to_datetime(df.ts, unit='s', utc=True)
    return df


@st.cache_data(ttl=7, show_spinner=False)
def ticker():
    v = get_json(f'{COINBASE}/ticker')
    px = float(v['price'])
    if not math.isfinite(px) or px <= 0:
        raise ValueError('Invalid Coinbase price')
    stamp = parse_time(v.get('time'))
    return px, stamp


@st.cache_data(ttl=8, show_spinner=False)
def live_market():
    result = get_json(f'{KALSHI}/markets', {'series_ticker': 'KXBTC15M', 'status': 'open', 'limit': 100})
    now = datetime.now(timezone.utc)
    options = []
    for m in result.get('markets', []):
        opened, closed = parse_time(m.get('open_time')), parse_time(m.get('close_time'))
        if (m.get('status') or '').lower() not in ('active', 'open') or closed is None:
            continue
        if closed > now and (opened is None or opened <= now):
            options.append((closed, m))
    return min(options, key=lambda entry: entry[0])[1] if options else None


@st.cache_data(ttl=8, show_spinner=False)
def market_by_ticker(symbol):
    return get_json(f'{KALSHI}/markets/{symbol}').get('market')


def parse_time(value):
    try:
        if not value:
            return None
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def quote(m, side, kind):
    if not m:
        return None
    field = f'{side}_{kind}'
    try:
        v = m.get(field + '_dollars')
        if v is not None and str(v) != '':
            n = float(v) * 100
        else:
            n = float(m[field])
        return round(n, 3) if math.isfinite(n) and 0 <= n <= 100 else None
    except (KeyError, TypeError, ValueError):
        return None


def market_strike(m):
    if not m:
        return None
    for field in ('floor_strike', 'cap_strike'):
        try:
            v = m.get(field)
            if v is not None and math.isfinite(float(v)) and float(v) > 0:
                return float(v)
        except (TypeError, ValueError):
            pass
    return None


def ema(series, length):
    return pd.Series(series, dtype=float).ewm(span=length, adjust=False).mean()


def rsi(series, length=14):
    dif = pd.Series(series, dtype=float).diff()
    up = dif.clip(lower=0).ewm(alpha=1/length, adjust=False).mean()
    dn = (-dif.clip(upper=0)).ewm(alpha=1/length, adjust=False).mean()
    both = up + dn
    result = (100 * up / both.replace(0, float('nan'))).fillna(50)
    return result


def atr(df, length=14):
    high, low, previous = df.high.astype(float), df.low.astype(float), df.close.astype(float).shift(1)
    true_range = pd.concat([high-low, (high-previous).abs(), (low-previous).abs()], axis=1).max(axis=1)
    return true_range.ewm(alpha=1/length, adjust=False).mean()


def turning_points(series, typ, min_separation=3):
    data = list(map(float, series))
    points = []
    for i in range(2, len(data)-2):
        window = data[i-2:i+3]
        candidate = data[i] == (max(window) if typ == 'high' else min(window))
        if not candidate:
            continue
        if points and i-points[-1] < min_separation:
            old = points[-1]
            if (typ == 'high' and data[i] > data[old]) or (typ == 'low' and data[i] < data[old]):
                points[-1] = i
        else:
            points.append(i)
    return points


def scan(df):
    """Rule-based candidate scanner; scores measure rule fit, NOT outcome probabilities."""
    if len(df) < 42:
        return []
    recent = df.tail(90).reset_index(drop=True)
    c, h, l, o = (recent[k].astype(float) for k in ('close','high','low','open'))
    price = float(c.iloc[-1]); scale = max(float(atr(recent).iloc[-1]), price*0.00008)
    findings = []

    def add(name, side, fit, details):
        findings.append({'pattern': name, 'side': side, 'fit': int(max(1, min(99, round(fit)))), 'details': details})

    # Doji & full-body impulse (confirmed candle is the penultimate candle).
    body = abs(float(c.iloc[-2]-o.iloc[-2])); rng = max(float(h.iloc[-2]-l.iloc[-2]), 1e-6)
    if body/rng <= 0.14:
        add('Doji', 'NEUTRAL', 75 + 20*(1-body/rng), 'Small candle body; direction needs confirmation')
    if body/rng >= .78 and rng >= 1.2*scale:
        add('Strong candle', 'UP' if c.iloc[-2]>o.iloc[-2] else 'DOWN', 65+min(25, body/rng*25), 'Large candle body, not a standalone entry signal')

    # Flag candidate: clear impulse followed by shallower consolidation in same time window.
    for direction in (1, -1):
        impulse = float(c.iloc[-10]-c.iloc[-27])*direction
        retrace = float(c.iloc[-2]-c.iloc[-10])*direction
        if impulse > 3*scale and -0.65*impulse < retrace < -0.08*impulse:
            vol_ratio = max(0, 1-abs(retrace)/impulse)
            add('Bull flag' if direction==1 else 'Bear flag', 'UP' if direction==1 else 'DOWN',
                60+25*vol_ratio, 'Impulse followed by a partial pullback; breakout unconfirmed')

    # Two well-separated pivot highs/lows with intervening rebound/pullback.
    for typ in ('high','low'):
        vals = h if typ=='high' else l
        pivots = turning_points(vals.tail(44).reset_index(drop=True), typ, 6)
        if len(pivots) < 2:
            continue
        p1, p2 = pivots[-2], pivots[-1]
        if p2-p1 < 6:
            continue
        chunk = vals.tail(44).reset_index(drop=True)
        first, second = float(chunk.iloc[p1]), float(chunk.iloc[p2])
        if abs(first-second) > max(1.7*scale, price*.0007):
            continue
        other = (l if typ=='high' else h).tail(44).reset_index(drop=True)
        valley = float(other.iloc[p1:p2+1].min() if typ=='high' else other.iloc[p1:p2+1].max())
        depth = (min(first,second)-valley) if typ=='high' else (valley-max(first,second))
        if depth >= 1.6*scale:
            add('Double top' if typ=='high' else 'Double bottom', 'DOWN' if typ=='high' else 'UP',
                66+min(22,depth/max(scale,1e-6)*3), 'Two similar swing levels; neckline break still required')

    # Three-swing head-and-shoulders candidate (inverse uses troughs).
    for typ in ('high', 'low'):
        vals = (h if typ=='high' else l).tail(65).reset_index(drop=True)
        piv = turning_points(vals,typ,5)
        if len(piv)<3:
            continue
        x,y,z = piv[-3:]
        left,head,right = map(lambda i: float(vals.iloc[i]),(x,y,z))
        shoulders_near = abs(left-right) <= 2.0*scale
        prominent = (head-max(left,right)>2.2*scale) if typ=='high' else (min(left,right)-head>2.2*scale)
        if shoulders_near and prominent and z-x>=12:
            add('Head & shoulders' if typ=='high' else 'Inverse head & shoulders',
                'DOWN' if typ=='high' else 'UP',72,
                'Three swing pivots with a prominent head; neckline confirmation required')

    # Triangle candidates: recent highs trend one way and lows converge.
    hh, ll = h.tail(22).reset_index(drop=True), l.tail(22).reset_index(drop=True)
    hi1, hi2 = float(hh.iloc[:11].max()), float(hh.iloc[11:].max())
    lo1, lo2 = float(ll.iloc[:11].min()), float(ll.iloc[11:].min())
    width1, width2 = hi1-lo1, hi2-lo2
    if width1 > 3*scale and width2 < width1*.80 and width2 > .5*scale:
        up_hi, up_lo = (hi2-hi1)/scale, (lo2-lo1)/scale
        if abs(up_hi) < 1.5 and up_lo > .8:
            add('Ascending triangle', 'UP', 70, 'Higher lows meeting relatively flat highs')
        elif abs(up_lo) < 1.5 and up_hi < -.8:
            add('Descending triangle', 'DOWN', 70, 'Lower highs meeting relatively flat lows')
        elif up_hi < -.8 and up_lo > .8:
            add('Symmetrical triangle', 'NEUTRAL', 68, 'Lower highs and higher lows; breakout direction unknown')
    return sorted(findings, key=lambda x:x['fit'], reverse=True)[:6]


def tiles(items):
    html = '<div class="sonar-grid">'
    for label, value, mood in items:
        html += (f'<div class="sonar-tile"><div class="sonar-k">{escape(str(label))}</div>'
                 f'<div class="sonar-v {escape(mood)}">{escape(str(value))}</div></div>')
    st.markdown(html + '</div>', unsafe_allow_html=True)


def chart(df, show_ema, show_levels, show_patterns):
    fig = go.Figure(go.Candlestick(x=df.date,open=df.open,high=df.high,low=df.low,close=df.close,
        increasing_line_color='#c4fa5f',decreasing_line_color='#ff7288',name='BTC',showlegend=False))
    if show_ema:
        for n, color in [(9,'#66d9e9'),(21,'#ffbb62')]:
            fig.add_trace(go.Scatter(x=df.date,y=ema(df.close,n),mode='lines',line={'color':color,'width':1.5},name=f'EMA {n}'))
    if show_levels:
        tail = df.tail(42)
        fig.add_hline(y=float(tail.high.max()),line_color='#f0b35f',line_dash='dash',opacity=.7)
        fig.add_hline(y=float(tail.low.min()),line_color='#9cdc65',line_dash='dash',opacity=.7)
    if show_patterns:
        matches = scan(df)
        if matches:
            name = matches[0]['pattern']
            fig.add_annotation(x=df.date.iloc[-1],y=float(df.high.iloc[-1]),text=name,
                showarrow=True,arrowhead=2,ax=-50,ay=-42,bgcolor='#263a36',font={'color':'#ecfff3','size':11})
    fig.update_layout(height=330,margin=dict(l=0,r=0,t=30,b=0),paper_bgcolor='#080e11',
        plot_bgcolor='#0d181b',font=dict(color='#e1ede8',size=11),xaxis_rangeslider_visible=False,
        legend=dict(orientation='h',y=1.18,x=0),xaxis=dict(gridcolor='#253538'),
        yaxis=dict(gridcolor='#253538',side='right',tickformat=',.0f'))
    st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False,'scrollZoom':False})


def config_panel():
    with st.sidebar:
        st.subheader('Chart settings')
        selected = st.selectbox('Candle interval',list(TF),index=0)
        show_ema = st.toggle('EMA 9 / EMA 21',True)
        show_levels = st.toggle('Support & resistance',True)
        show_patterns = st.toggle('Show top pattern on chart',True)
        st.subheader('Late-entry paper rules')
        min_ask = st.number_input('Minimum entry ask (¢)',1.0,99.0,80.0,step=1.0)
        max_ask = st.number_input('Maximum entry ask (¢)',1.0,99.0,96.0,step=1.0)
        seconds = st.number_input('Entry window: remaining seconds ≤',15,900,180,step=15)
        min_remaining = st.number_input('Do not enter below (seconds)',0,300,25,step=5)
        gap = st.number_input('Minimum BTC-to-strike gap ($)',0.,10000.,100.,step=10.)
        max_spread = st.number_input('Maximum bid/ask spread (¢)',0.1,50.0,5.0,step=0.5)
        rsi_gate = st.toggle('Require RSI direction confirmation',False)
        st.subheader('Paper exit settings')
        tp = st.number_input('Take-profit bid (¢)',1.0,99.0,97.0,step=1.0)
        sl = st.number_input('Stop-loss bid (¢)',1.0,99.0,70.0,step=1.0)
        qty = st.number_input('Contracts per paper trade',1,1000,10)
        st.caption('The Kalshi market resolves using its defined reference, not necessarily Coinbase. The $ gap is a proxy only.')
    return dict(timeframe=selected,ema=show_ema,levels=show_levels,patterns=show_patterns,
        min_ask=min_ask,max_ask=max_ask,window=seconds,min_remaining=min_remaining,gap=gap,
        spread=max_spread,rsi_gate=rsi_gate,tp=tp,sl=sl,qty=qty)


def evaluate(px, strike, remaining, quotes, trend, rsi_value, settings):
    reasons=[]
    side = 'UP' if strike is not None and px > strike else 'DOWN' if strike is not None and px < strike else None
    if side is None:
        reasons.append('Strike missing or price exactly at strike')
    gap = abs(px-strike) if strike is not None else None
    if gap is None or gap < settings['gap']:
        reasons.append('BTC distance from strike too small')
    if remaining <= settings['min_remaining'] or remaining > settings['window']:
        reasons.append('Outside permitted entry countdown')
    ask, bid = quotes.get(side, (None,None)) if side else (None,None)
    if ask is None or bid is None or ask <= 0 or bid <= 0:
        reasons.append('Missing executable market quotes')
    else:
        if not (settings['min_ask'] <= ask <= settings['max_ask']):
            reasons.append('Ask outside entry range')
        if ask-bid > settings['spread'] or ask < bid:
            reasons.append('Bid/ask spread too wide or invalid')
    if side is not None and trend != side:
        reasons.append('EMA 9/21 trend disagrees')
    if settings['rsi_gate'] and side=='UP' and rsi_value < 50:
        reasons.append('RSI not above 50')
    if settings['rsi_gate'] and side=='DOWN' and rsi_value > 50:
        reasons.append('RSI not below 50')
    if settings['min_ask'] > settings['max_ask']:
        reasons.append('Entry ask range invalid')
    if settings['sl'] >= settings['tp']:
        reasons.append('TP must exceed SL')
    return side, ask, bid, reasons


def cash_pnl(pos, exit_price):
    return round((exit_price-pos['entry'])*pos['qty']/100,2)


def init_state():
    if 'open_paper' not in st.session_state:
        st.session_state.open_paper = None
    if 'paper_history' not in st.session_state:
        st.session_state.paper_history = []


def record_exit(pos, price, reason):
    result = dict(pos)
    result.update(exit_bid=price, exit_reason=reason, closed_utc=datetime.now(timezone.utc).isoformat(),
                  pnl_before_fees=cash_pnl(pos,price) if price is not None else None)
    st.session_state.paper_history.insert(0,result)
    st.session_state.open_paper = None


def manage_position(market, settings):
    pos = st.session_state.open_paper
    if not pos:
        return
    # If the active ticker rolled over, request the actual position's market instead.
    current = market if market and market.get('ticker') == pos['ticker'] else None
    if current is None:
        try:
            current = market_by_ticker(pos['ticker'])
        except Exception:
            current = None
    bid = quote(current, 'yes' if pos['side']=='UP' else 'no', 'bid')
    status = (current or {}).get('status','unknown')
    settled = (current or {}).get('result','').lower()
    st.markdown('#### Open simulated position')
    tiles([('Side',pos['side'],'good'),('Entry ask',f"{pos['entry']:g}¢",''),
           ('Current bid',f'{bid:g}¢' if bid is not None else 'N/A',''),
           ('Unrealized P&L',f"${cash_pnl(pos,bid):+,.2f}" if bid is not None else 'N/A','')])
    st.caption(f"{pos['ticker']} · {pos['qty']} contracts · {status} · paper-only, before fees")
    if settled in ('yes','no'):
        payout = 100.0 if (pos['side']=='UP') == (settled=='yes') else 0.0
        record_exit(pos,payout,'SETTLEMENT (simulated payout)')
        st.success(f'Contract settled: {settled.upper()} · position recorded at {payout:g}¢ payout, before fees.')
    elif bid is not None and (status in ('active','open')) and bid >= settings['tp']:
        record_exit(pos,bid,'TAKE PROFIT (bid snapshot)')
        st.success(f'Paper take-profit triggered at displayed {bid:g}¢ bid. Not a guaranteed fill.')
    elif bid is not None and (status in ('active','open')) and bid <= settings['sl']:
        record_exit(pos,bid,'STOP LOSS (bid snapshot)')
        st.warning(f'Paper stop-loss triggered at displayed {bid:g}¢ bid. Not a guaranteed fill.')
    else:
        if status not in ('active','open'):
            st.warning('Trading closed or live quote unavailable. Awaiting a confirmed result; no assumed exit fill.')
        if st.button('Manually close simulated position',use_container_width=True):
            if bid is not None and status in ('active','open'):
                record_exit(pos,bid,'MANUAL (bid snapshot)')
            else:
                record_exit(pos,None,'MANUAL (no live fill quote)')
            st.rerun(scope='fragment')


settings = config_panel()
init_state()
st.title('SONAR / BTC–USD')
st.markdown('<div class="sonar-sub">LIVE MARKET WORKSPACE <span class="sonar-chip">KALSHI 15M</span> <span class="sonar-chip">PAPER ONLY</span></div>',unsafe_allow_html=True)

@st.fragment(run_every='10s')
def dashboard():
    try:
        df = candles(TF[settings['timeframe']])
        px, px_at = ticker()
    except Exception as exc:
        st.error('Coinbase feed unavailable. No new trade signals. ' + str(exc))
        return
    ago = (datetime.now(timezone.utc)-px_at).total_seconds() if px_at else None
    stale = ago is not None and (ago > 90 or ago < -30)
    rsi_val = float(rsi(df.close).iloc[-1]); fast=float(ema(df.close,9).iloc[-1]); slow=float(ema(df.close,21).iloc[-1])
    trend='UP' if fast > slow else 'DOWN' if fast < slow else 'FLAT'
    matches = scan(df)

    try:
        m = live_market(); feed_error=None
    except Exception as exc:
        m=None;feed_error=str(exc)
    strike=market_strike(m)
    close=parse_time(m.get('close_time')) if m else None
    remaining=max(0,int((close-datetime.now(timezone.utc)).total_seconds())) if close else None
    quotes={side:(quote(m,key,'ask'),quote(m,key,'bid')) for side,key in [('UP','yes'),('DOWN','no')]}

    tiles([('BTC price',f'${px:,.2f}',''),('EMA trend',trend,'good' if trend=='UP' else 'bad' if trend=='DOWN' else ''),
           ('RSI 14',f'{rsi_val:.1f}',''),('Interval',settings['timeframe'],'')])
    if stale:
        st.warning('Coinbase ticker timestamp is stale; entry disabled.')
    tab_chart,tab_scan,tab_paper = st.tabs(['📈 Chart', '🔎 Patterns', '📒 Paper trades'])
    with tab_chart:
        chart(df,settings['ema'],settings['levels'],settings['patterns'])
        support,resistance = float(df.tail(42).low.min()),float(df.tail(42).high.max())
        st.caption(f'Support ${support:,.2f} · Resistance ${resistance:,.2f} · Recent candle range, not guaranteed levels')
    with tab_scan:
        if not matches:
            st.info('No structure passed the scanner thresholds. This is normal, not a feed error.')
        else:
            for p in matches:
                st.markdown(f"**{p['pattern']}** · {p['side']} · rule-fit **{p['fit']}/100**")
                st.caption(p['details'])
        st.caption('Rule-fit scores are NOT probability, confidence of profit, or independently validated win rates. Flag and double-top/bottom names indicate candidates, not confirmed breakouts.')
    with tab_paper:
        if st.session_state.open_paper:
            manage_position(m,settings)
        else:
            st.info('No open paper trade.')
        if st.session_state.paper_history:
            st.markdown('#### Simulated trade history')
            st.dataframe(pd.DataFrame(st.session_state.paper_history),hide_index=True,use_container_width=True)
            if st.button('Clear completed paper history'):
                st.session_state.paper_history=[]
                st.rerun(scope='fragment')
        st.caption('Paper trades are held only in this Streamlit session. They may disappear when the app restarts or the session expires. Quotes are snapshots; fees, slippage and partial fills are excluded.')

    st.markdown('### Kalshi · BTC 15-minute contract')
    if not m:
        st.warning('No active 15m Kalshi market returned.' + (f' Feed error: {feed_error}' if feed_error else ''))
        st.markdown('<div class="sonar-status nogo"><strong>NO TRADE</strong><p>Live Kalshi contract required.</p></div>',unsafe_allow_html=True)
        return
    st.caption(f"{m.get('ticker','Unknown')} · {(m.get('title') or 'BTC 15-minute up/down')} · status {m.get('status','unknown')}")
    up_ask,up_bid=quotes['UP'];down_ask,down_bid=quotes['DOWN']
    def fmtbid(bid,ask):
        return f'{bid:g}¢ / {ask:g}¢' if bid is not None and ask is not None else 'N/A'
    tiles([('Time remaining',f'{remaining//60:02}:{remaining%60:02}' if remaining is not None else 'N/A','warn'),
           ('Market strike',f'${strike:,.2f}' if strike is not None else 'N/A',''),
           ('BTC − strike',f'${px-strike:+,.2f}' if strike is not None else 'N/A',''),
           ('Market status',str(m.get('status','N/A')).upper(),'good'),
           ('UP bid / ask',fmtbid(up_bid,up_ask),''),('DOWN bid / ask',fmtbid(down_bid,down_ask),'')])
    side,ask,bid,reasons = evaluate(px,strike,remaining if remaining is not None else 0,quotes,trend,rsi_val,settings)
    if stale:
        reasons.append('Stale underlying price feed')
    if st.session_state.open_paper:
        reasons.append('Paper position already open')
    eligible=not reasons
    heading = f'WATCH {side}' if eligible else 'NO TRADE'
    st.markdown(f'<div class="sonar-status {"" if eligible else "nogo"}"><strong>{escape(heading)}</strong><p>{escape("All configured entry filters passed — not a proven prediction." if eligible else " · ".join(reasons))}</p></div>',unsafe_allow_html=True)
    st.markdown('<div class="sonar-note">Decision checks compare Coinbase BTC price with the Kalshi strike. Coinbase is NOT the guaranteed Kalshi settlement reference. Do not treat a $ gap or pattern-fit score as a win probability.</div>',unsafe_allow_html=True)
    if eligible:
        st.caption(f'{settings["qty"]} paper {side} contracts · simulated buy at {ask:g}¢ ask · current bid {bid:g}¢ · paper TP {settings["tp"]:g}¢ · SL {settings["sl"]:g}¢')
    if st.button(f'Open {side} paper trade' if eligible else 'Paper entry unavailable',
                 type='primary',disabled=not eligible,use_container_width=True):
        st.session_state.open_paper=dict(ticker=m['ticker'],side=side,entry=ask,qty=settings['qty'],
                                         opened_utc=datetime.now(timezone.utc).isoformat())
        st.rerun(scope='fragment')
    if st.session_state.open_paper:
        st.caption('Your position is in the Paper trades tab. TP/SL checks run on each page refresh.')
    st.caption('Market data refreshes approximately every 10 seconds while the app is open. No automatic live orders.')

dashboard()
